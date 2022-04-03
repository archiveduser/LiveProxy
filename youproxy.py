import subprocess
import time
import logging
import threading
import re
import requests
import json
import random
import os


logging.basicConfig(level=logging.INFO,
                    format="[%(levelname)s] [%(asctime)s] %(message)s",
                    datefmt='%Y-%m-%d %H:%M:%S'
                    )


class YoutubeProxy:

    def __init__(self, task):
        logging.info("LOAD TASK %s" % str(task))
        self.name = task['name']
        self.channel = task['channel']
        self.video = task['video']
        self.audio = task['audio']
        self.notify = task['notify']
        self.status = False

    def qq_private_notify(self, to, message):
        try:
            r = requests.get(
                "https://cqhttp.imea.me/send_private_msg?user_id=%s&message=%s" % (to, message))
            content = r.content.decode('utf8')
            if json.loads(content)['status'] != 'ok':
                raise Exception(content)
            logging.info(f"[{self.name}]SEND PRIVATE NOTIFY SUCCESS")
        except Exception as e:
            logging.error(f"[{self.name}]SEND PRIVATE NOTIFY ERROR {str(e)}")

    def qq_group_notify(self, to, message):
        try:
            r = requests.get(
                "https://cqhttp.imea.me/send_group_msg?group_id=%s&message=%s" % (to, message))
            content = r.content.decode('utf8')
            if json.loads(content)['status'] != 'ok':
                raise Exception(content)
            logging.info(f"[{self.name}]SEND GROUP NOTIFY SUCCESS")
        except Exception as e:
            logging.error(f"[{self.name}]SEND GROUP NOTIFY ERROR {str(e)}")

    def get_unused_port(self):
        while True:
            port = random.randint(11000, 61000)
            r = os.popen("sudo netstat -tunlp|grep %s" % port)
            if len(r.read()) == 0:
                logging.info(f"[{self.name}]GET UNUSED PORT {port}")
                return port

    def check_youtube_live(self):
        try:
            response = requests.get(
                "https://www.youtube.com/channel/%s" % self.channel, timeout=10)
            content = response.content.decode('utf8')
            r = re.search(r'var ytInitialData = (.*);</script>', content)
            data = json.loads(r.group(1))
            c = data['contents']['twoColumnBrowseResultsRenderer']['tabs'][0]['tabRenderer']['content']['sectionListRenderer'][
                'contents'][0]['itemSectionRenderer']['contents'][0]
            # print(c)
            lives = []
            if 'items' in c['channelFeaturedContentRenderer']:
                items = c['channelFeaturedContentRenderer']['items']
                for item in items:
                    video = item['videoRenderer']
                    live = {
                        'id': video['videoId'],
                        'title': video['title']['runs'][0]['text'],
                    }
                    logging.info(f"[{self.name}]FOUND LIVE {live['title']}")

                    lives.append(live)
            else:
                item = c['channelVideoPlayerRenderer']
                live = {
                    'id': item['videoId'],
                    'title': item['title']['runs'][0]['text'],
                }
                logging.info(f"[{self.name}]FOUND LIVE {live['title']}")
                lives.append(live)

            if len(lives) > 0:
                return lives
            else:
                return None

        except Exception as e:
            logging.debug(f"[{self.name}]CHECK LIVE ERROR {str(e)}")
            return None

    def start_stream_proxy(self, url, port):
        logging.info(f"[{self.name}]START STREAM PROXY")
        p = subprocess.Popen(['/usr/local/bin/streamlink', url, 'best',
                              '--player-external-http',
                              '--player-external-http-port',
                              str(port), '--retry-open', '30'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

        return p

    def start_rtmp_push(self, port, vkey, akey=None):
        command = ['ffmpeg', '-re', '-rw_timeout', '2000000', '-i', 'http://localhost:%s' % port,
                   '-c:v', 'copy', '-c:a', 'copy', '-f', 'flv',
                   'rtmp://localhost:1935/live/%s' % vkey]
        if akey is not None:
            logging.info(f"[{self.name}]ENABLE AUDIO PROXY")
            command += ['-vn', '-c:a', 'copy', '-f', 'flv',
                        'rtmp://localhost:1935/live/%s' % akey]
        logging.info(f"[{self.name}]START RTMP PUSH")
        p = subprocess.Popen(command, stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT)

        return p

    def notify_live_status(self):
        current_status = os.path.exists('/tmp/hls/%s.m3u8' % self.video)
        if current_status == self.status:
            return

        if current_status:
            proxy_video_url = "https://stream-01.imea.me/hls/%s.m3u8" % self.video
            message = "[LiveWatchCat]\n转播任务开始\n"
            message += "标题: %s\n" % self.live['title']
            message += "链接: %s\n" % self.url
            message += "转播: %s\n" % proxy_video_url

            if self.audio:
                message += "音频: %s\n" % "https://stream-01.imea.me/hls/%s.m3u8" % self.audio

            message += "时间: %s" % time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime())

            logging.info(f"[{self.name}]SEND LIVE START NOTIFY")
            for m in self.notify:
                if m['type'] == 'private':
                    self.qq_private_notify(m['to'], message)
                elif m['type'] == 'group':
                    self.qq_group_notify(m['to'], message)
                else:
                    pass
        else:
            logging.info(f"[{self.name}]SEND LIVE STOP NOTIFY")
            message = "[LiveWatchCat]\n转播任务停止\n"
            message += "标题: %s\n" % self.live['title']
            for m in self.notify:
                if m['type'] == 'private':
                    self.qq_private_notify(m['to'], message)
                elif m['type'] == 'group':
                    self.qq_group_notify(m['to'], message)
                else:
                    pass
        self.status = current_status

    def start_live_proxy(self, url, vkey, akey):
        port = self.get_unused_port()
        stream = self.start_stream_proxy(url, port)
        try_count = 0
        while stream.poll() is None:
            if try_count > 5:
                break
            logging.info(f"[{self.name}]START RTMP PUSH {try_count}")
            push = self.start_rtmp_push(port, vkey, akey)
            time.sleep(1)
            while push.poll() is None:
                self.notify_live_status()
                time.sleep(1)
            push.terminate()
            logging.info(f"[{self.name}]RTMP PUSH STOPED")
            try_count += 1
        stream.terminate()
        self.status = False
        logging.info(f"[{self.name}]STREAM PROXY STOPED")

    def run_task(self):
        logging.info(f"[{self.name}]START TASK")
        while True:
            lives = self.check_youtube_live()
            if lives is None:
                logging.info(f"[{self.name}]LIVE NOT START")
                time.sleep(300 + random.randint(0, 60))
                # time.sleep(10)
                continue
            self.live = lives[0]
            self.url = 'https://www.youtube.com/watch?v=%s' % self.live['id']
            logging.info(f"[{self.name}]PROXY USE URL {self.url}")
            if self.audio:
                logging.info(f"[{self.name}]PROXY AUDIO KEY {self.audio}")

            logging.info(f"[{self.name}]LIVE PROXT START")
            self.start_live_proxy(self.url, self.video, self.audio)
            time.sleep(5)

    def run_task_thread(self):
        threading.Thread(target=self.run_task).start()


if __name__ == "__main__":
    tasks = []
    with open("config.json", "r", encoding='utf8') as f:
        tasks = json.loads(f.read())

    for task in tasks:
        YoutubeProxy(task).run_task_thread()
