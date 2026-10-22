"""A local Hebrew form for creating downloadable name-stencil ZIP files."""
import argparse
import html
import json
import tempfile
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from stencils import archive_output, export_item, make_name

PAGE = """<!doctype html><html lang="he" dir="rtl"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>שבלונה לשם שלי</title>
<style>body{font-family:Arial,sans-serif;background:#f7f5ef;color:#283d42;max-width:640px;margin:8vh auto;padding:24px;line-height:1.7}h1{font-size:32px}form{background:white;padding:28px;border-radius:18px}label{display:block;margin-top:16px}input,select,button{font:inherit;padding:12px;border:1px solid #a3b7ac;border-radius:8px;box-sizing:border-box;width:100%}button{background:#294a43;color:white;margin-top:24px;cursor:pointer}.note{font-size:14px}.error{background:#ffe1d8;padding:12px;border-radius:8px}</style>
<h1>שבלונה לשם שלי</h1><p>כותבים שם בעברית ומורידים קבצים להדפסת תלת־ממד, עם חצים ומספרי שלבים.</p>
{error}<form method="post" action="/generate"><label for="name">השם</label><input id="name" name="name" required maxlength="40" placeholder="למשל: נגה" autocomplete="off">
<label for="thickness">עובי השבלונה</label><select id="thickness" name="thickness"><option value="1.8">1.8 מ״מ — הגרסה הדקה לניסיון</option><option value="2.4">2.4 מ״מ</option><option value="3.2">3.2 מ״מ</option></select>
<button>יצירת שבלונה והורדת הקבצים</button><p class="note">היצירה עשויה להימשך כמה שניות. שם ארוך מדי יצטרך פיצול לשתי שבלונות.</p></form>
<p class="note">החבילה כוללת תצוגה מקדימה, הוראות וקבצים לצבע אחד או לשני צבעים. את הקובץ בודקים וחותכים בסלייסר לפני הדפסה. הגרסה עדיין בניסוי.</p>
<p class="note">השם מעובד במחשב הזה בלבד. אין שירות ענן ואין שליחה למדפסת.</p></html>"""


class Handler(BaseHTTPRequestHandler):
    def page(self, error="", status=200):
        text = PAGE.replace("{error}", '<p class="error">' + html.escape(error) + '</p>' if error else "")
        self.respond(text.encode(), "text/html; charset=utf-8", status)

    def respond(self, content, content_type, status=200, attachment=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if attachment:
            self.send_header("Content-Disposition", 'attachment; filename="' + attachment + '"')
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        if self.path == "/":
            self.page()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/generate":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError("בקשה גדולה מדי או ריקה.")
            origin = self.headers.get("Origin")
            if origin and urllib.parse.urlparse(origin).netloc != self.headers.get("Host"):
                self.send_error(403)
                return
            params = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
            name = params.get("name", [""])[0]
            thickness = float(params.get("thickness", ["1.8"])[0])
            with tempfile.TemporaryDirectory(prefix="hebrew-name-") as tmp:
                output = export_item(make_name(name, thickness), Path(tmp) / "stencil")
                archive = archive_output(output, Path(tmp) / "hebrew-name-stencil.zip")
                self.respond(archive.read_bytes(), "application/zip", attachment=archive.name)
        except ValueError as exc:
            self.page(str(exc), 400)
        except Exception:
            self.page("יצירת הקובץ נכשלה. אפשר לנסות שם קצר יותר או להריץ את המחולל משורת הפקודה לפרטים.", 500)
            raise

    def log_message(self, fmt, *args):
        # Names are not put in URLs or written to request logs.
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    server = HTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}"
    print("מחולל השמות: " + url + " — לסיום Ctrl+C", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
