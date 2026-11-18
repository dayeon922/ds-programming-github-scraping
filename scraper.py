"""GitHub の Google 組織のリポジトリ情報をスクレイピングして SQLite に保存する。

取得する情報: リポジトリ名 / 主要な言語 / スターの数
- GitHub API は使わず、ページの HTML に埋め込まれた JSON
  (<script data-target="react-app.embeddedData">) を解析する
- サーバーに負荷をかけないよう、リクエストごとに time.sleep(1) を入れる

使い方:
    python scraper.py                  # 全ページ取得 -> DB 保存 -> SELECT 表示
    python scraper.py --max-pages 2    # 動作確認用に 2 ページだけ取得
    python scraper.py --show-only      # 取得せず DB の中身だけ表示
"""

import argparse
import json
import sqlite3
import time

import requests
from bs4 import BeautifulSoup

URL = "https://github.com/orgs/google/repositories"
DB_PATH = "google_repos.db"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; university-assignment-scraper/1.0)"}


def fetch_page(session, page, max_retries=6):
    """page ページ目の HTML を返す。

    429 (Too Many Requests) が返ったら、待ってから再試行する。
    Retry-After ヘッダーがあればその秒数、無ければ 60 秒 × 試行回数だけ待つ。
    """
    for attempt in range(1, max_retries + 1):
        response = session.get(URL, params={"page": page}, headers=HEADERS, timeout=30)
        if response.status_code != 429:
            response.raise_for_status()
            return response.text
        try:
            wait = int(response.headers.get("Retry-After", ""))
        except ValueError:
            wait = 60 * attempt
        wait = max(wait, 30)
        print(f"page {page}: 429 Too Many Requests -> {wait} 秒待って再試行 ({attempt}/{max_retries})")
        time.sleep(wait)
    response.raise_for_status()  # 再試行しても駄目なら例外を出す


def parse_page(html):
    """HTML から (リポジトリのリスト, 総ページ数) を取り出す。

    リポジトリは (name, language, stars) のタプル。言語が無ければ language は None。
    """
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", attrs={"data-target": "react-app.embeddedData"})
    if tag is None or not tag.string:
        raise RuntimeError("embeddedData が見つかりません。HTML の構造が変わった可能性があります。")
    route = json.loads(tag.string)["payload"]["orgReposPageRoute"]

    repos = []
    for repo in route["repositories"]:
        language = (repo.get("primaryLanguage") or {}).get("name")
        repos.append((repo["name"], language, repo.get("starsCount", 0)))
    return repos, route["pageCount"]


def init_db(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS repositories (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            name     TEXT NOT NULL UNIQUE,
            language TEXT,
            stars    INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.commit()


def save_repositories(conn, repos):
    """再実行しても重複しないよう、同名なら上書き(UPSERT)で保存する。"""
    conn.executemany(
        """
        INSERT INTO repositories (name, language, stars) VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            language = excluded.language,
            stars    = excluded.stars
        """,
        repos,
    )
    conn.commit()


def scrape_and_save(conn, max_pages=None, start_page=1):
    """start_page から順に取得し、1 ページごとに DB へ保存する。"""
    with requests.Session() as session:
        page, total_pages = start_page, None
        while total_pages is None or page <= total_pages:
            if max_pages is not None and page > max_pages:
                break
            html = fetch_page(session, page)
            time.sleep(1)  # 課題の指定: リクエストごとに必ず 1 秒待つ
            repos, total_pages = parse_page(html)
            save_repositories(conn, repos)
            print(f"page {page}/{total_pages}: {len(repos)} 件保存")
            page += 1


def show_repositories(conn):
    """保存したデータを SELECT 文で表示する。"""
    rows = conn.execute(
        "SELECT name, language, stars FROM repositories ORDER BY stars DESC, name"
    ).fetchall()
    print(f"{'name':<45} {'language':<20} {'stars':>8}")
    print("-" * 75)
    for name, language, stars in rows:
        print(f"{name:<45} {language or '-':<20} {stars:>8}")
    print(f"\n合計: {len(rows)} 件")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--start-page", type=int, default=1, help="途中から再開する時に指定")
    parser.add_argument("--db", default=DB_PATH)
    parser.add_argument("--show-only", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        init_db(conn)
        if not args.show_only:
            scrape_and_save(conn, args.max_pages, args.start_page)
        show_repositories(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
