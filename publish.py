"""Облачный автопостинг Instagram для @viktoriashow.official (запускается GitHub Actions каждые 10 минут).

Очередь — папки queue/<id>/ с post.json и готовыми файлами (их заранее готовит instagram.ps1 -Add на ноутбуке).
Instagram сам скачивает файлы по ссылкам raw.githubusercontent.com, поэтому они лежат в этом публичном репозитории
до публикации и удаляются сразу после неё.
"""
import datetime
import glob
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

GRAPH = 'https://graph.instagram.com/v21.0'
RAW = 'https://raw.githubusercontent.com/viktoriakrasova01-glitch/viktoriashow-media/main/'
TOKEN = os.environ['IG_TOKEN']
USER_ID = os.environ['IG_USER_ID']
VK_TOKEN = os.environ.get('VK_TOKEN')
VK_NOTIFY = 8742473          # кому во ВК приходят уведомления (Виктория)


def ig(method, path, params=None):
    params = dict(params or {}, access_token=TOKEN)
    data = urllib.parse.urlencode(params)
    try:
        if method == 'GET':
            req = urllib.request.Request(f'{GRAPH}/{path}?{data}')
        else:
            req = urllib.request.Request(f'{GRAPH}/{path}', data=data.encode(), method='POST')
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f'Instagram {path} — {e.code} {e.read().decode(errors="replace")}') from None


def wait_container(cid):
    for _ in range(120):
        s = ig('GET', cid, {'fields': 'status_code,status'})
        if s.get('status_code') == 'FINISHED':
            return
        if s.get('status_code') in ('ERROR', 'EXPIRED'):
            raise RuntimeError(f'Instagram не принял файл: {s.get("status")}')
        time.sleep(5)
    raise RuntimeError('Instagram слишком долго обрабатывает видео.')


def is_video(f):
    return f.lower().endswith(('.mp4', '.mov'))


def publish_post(post, folder):
    urls = [RAW + urllib.parse.quote(f'{folder}/{f}') for f in post['files']]
    if len(urls) == 1 and is_video(post['files'][0]):
        c = ig('POST', f'{USER_ID}/media', {'media_type': 'REELS', 'video_url': urls[0], 'caption': post['text'], 'share_to_feed': 'true'})
    elif len(urls) == 1:
        c = ig('POST', f'{USER_ID}/media', {'image_url': urls[0], 'caption': post['text']})
    else:
        kids = []
        for f, u in list(zip(post['files'], urls))[:10]:
            p = {'media_type': 'VIDEO', 'video_url': u} if is_video(f) else {'image_url': u}
            k = ig('POST', f'{USER_ID}/media', dict(p, is_carousel_item='true'))
            wait_container(k['id'])
            kids.append(k['id'])
        c = ig('POST', f'{USER_ID}/media', {'media_type': 'CAROUSEL', 'children': ','.join(kids), 'caption': post['text']})
    wait_container(c['id'])
    pub = ig('POST', f'{USER_ID}/media_publish', {'creation_id': c['id']})
    return ig('GET', pub['id'], {'fields': 'permalink'})['permalink']


def publish_story(post, folder):
    f = post.get('story')
    if not f:
        return
    url = RAW + urllib.parse.quote(f'{folder}/{f}')
    p = {'media_type': 'STORIES', ('video_url' if is_video(f) else 'image_url'): url}
    c = ig('POST', f'{USER_ID}/media', p)
    wait_container(c['id'])
    ig('POST', f'{USER_ID}/media_publish', {'creation_id': c['id']})


def notify(text):
    if not VK_TOKEN:
        return
    data = urllib.parse.urlencode({'peer_id': VK_NOTIFY, 'random_id': int(time.time() * 1000) % 2147483647,
                                   'message': text, 'access_token': VK_TOKEN, 'v': '5.199'}).encode()
    try:
        urllib.request.urlopen('https://api.vk.com/method/messages.send', data=data, timeout=30).read()
    except Exception as e:  # уведомление не должно ронять публикацию
        print('Не смогла отправить уведомление во ВК:', e)


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    for path in sorted(glob.glob('queue/*/post.json')):
        folder = os.path.dirname(path).replace('\\', '/')
        with open(path, encoding='utf-8') as fh:
            post = json.load(fh)
        if post.get('status') != 'ждёт' or datetime.datetime.fromisoformat(post['when']) > now:
            continue
        print('Публикую', post['id'])
        try:
            post['permalink'] = publish_post(post, folder)
            post['status'] = 'вышел'
            notify(f'✅ Вышел пост в Instagram: {post["permalink"]}')
            try:
                time.sleep(30)
                publish_story(post, folder)
            except Exception as e:
                print('Сторис не вышла:', e)
                notify('⚠️ Пост вышел, а сторис к нему — нет. Напишите Claude: «почему не вышла сторис?»')
        except Exception as e:
            post['status'] = 'ошибка'
            post['error'] = str(e)[:500]
            print('Ошибка:', e)
            notify(f'⚠️ Не вышел пост в Instagram «{post["id"]}». Напишите Claude: «почему не вышло в Instagram?»')
        post['done_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(post, fh, ensure_ascii=False, indent=2)
        if post['status'] == 'вышел':     # файлы больше не нужны — убираем из публичного репозитория
            for f in os.listdir(folder):
                if f != 'post.json':
                    os.remove(os.path.join(folder, f))


if __name__ == '__main__':
    main()
