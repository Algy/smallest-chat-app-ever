from gevent import monkey
monkey.patch_all()

import time
import random

from threading import Lock, Condition
from flask import Flask, request, jsonify, render_template
from gevent.pywsgi import WSGIServer

app = Flask(__name__)

AUTHORS = [
    "John",
    "Einstein",
    "Park",
    "Faker"
]

class Message(object):
    def __init__(self, id, author, content, uploaded_at):
        self.id = id
        self.author = author
        self.content = content
        self.uploaded_at = uploaded_at

    @staticmethod
    def parse(d):
        try:
            if ("id" in d and not isinstance(d["id"], (int, long))) or \
               not isinstance(d["author"], (str, unicode)) or \
               not isinstance(d["content"], (str, unicode)) or \
               ("uploaded_at" in d and not isinstance(d["uploaded_at"], (int, long, float))):
                raise ValueError("Invalid Format")
            msg = Message(int(d.get("id", -1)), 
                          d["author"], 
                          d["content"], 
                          float(d.get("uploaded_at", time.time() / 1000.)))
            return msg
        except KeyError as exc:
            raise ValueError("Invalid Format: %s"%str(exc))

    def present(self):
        return {
            "id": self.id,
            "author": self.author,
            "content": self.content,
            "uploaded_at": self.uploaded_at
        }


NLOG = 10000
TIMEOUT_SECONDS = 30
class LogData(object):
    def __init__(self):
        self.lock = Lock()
        self.messages = []
        self.last_id = -1

    def append(self, msg):
        with self.lock:
            self.last_id += 1
            msg.id = self.last_id
            self.messages.append(msg)
            return self.last_id

    def has_more_data(self, id):
        with self.lock:
            return self.last_id > id

    def get_more_data(self, id):
        with self.lock:
            lo = 0
            lower_bound = len(self.messages)
            hi = len(self.messages) - 1 
            while lo <= hi:
                mid = (lo + hi) / 2
                if self.messages[mid].id > id:
                    lower_bound = mid
                    hi = mid - 1
                else:
                    lo = mid + 1
            return self.messages[lower_bound:]

    def get_data(self, limit):
        return self.messages[-limit:]


log_data = LogData()
cond = Condition()
def notify_theres_more_data():
    cond.acquire()
    cond.notify_all()
    cond.release()

def wait_for_new_data(timeout):
    cond.acquire()
    cond.wait(timeout=timeout)
    cond.release()

@app.route("/api/longpoll/chat/new/<id>")
def longpoll_chat_new(id):
    id = int(id)
    print "LONGPOLL ID", id
    if not log_data.has_more_data(id):
        print "WAIT FOR ID:", id
        wait_for_new_data(TIMEOUT_SECONDS)
    return jsonify(success=True, result=[msg.present() for msg in log_data.get_more_data(id)])


@app.route("/api/chat/new/<int:id>")
def chat_new(id):
    return jsonify(success=True, result=[msg.present() for msg in log_data.get_more_data(id)])


@app.route("/api/chat", methods=["GET", "POST"])
def get_chat():
    if request.method == "POST":
        try:
            d = request.get_json()
            if d is None:
                raise ValueError("JSON request data hasn't been received")
            msg = Message.parse(d)
            log_data.append(msg)
            notify_theres_more_data()
            return jsonify(success=True)
        except ValueError as exc:
            resp = jsonify(success=False, reason=str(exc))
            resp.status_code = 400
            return resp
    else:
        limit = int(request.args.get("limit", 20))
        return jsonify(success=True, 
                       result=[msg.present() for msg in log_data.get_data(limit)])


@app.route("/")
def index():
    return render_template("index.html", nickname=random.choice(AUTHORS))


application = app
if __name__ == '__main__':
    http_server = WSGIServer(('', 8080), application)
    http_server.serve_forever()
    app.run(debug=True)
