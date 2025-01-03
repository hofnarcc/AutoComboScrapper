import requests
import re
import subprocess
import os
import urllib3
import datetime
import threading
import time
import sys
import tkinter as tk
from tkinter import ttk, messagebox
from bs4 import BeautifulSoup
from pathvalidate import sanitize_filename
import queue
import pickle
import logging
import sqlite3
from urllib.parse import quote
import shutil
import zipfile
import tarfile
import random
from googlesearch import search

# Disable warnings from urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler("debug.log", 'a', 'utf-8'),
        logging.StreamHandler()
    ]
)

# Global variables
agent = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/123.0.0.0 Safari/537.36'
    )
}
scraped = 0
scraped_lock = threading.Lock()
pages = 0
current_date = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
result_folder = os.path.join("combos", current_date)
pause_event = threading.Event()
stop_event = threading.Event()

# Database variables (initialized later based on checkbox)
db_connection = None
db_cursor = None

class leech:
    use_database = True  # Default to True
    app_instance = None  # Reference to the main app instance for GUI updates

    @staticmethod
    def save(output, thread, host, alr=False):
        global scraped
        if not alr:
            filtered = [
                line.strip()
                for line in output.split('\n')
                if re.match(r'^[^\s@:]+@[^\s@:]+\.[^\s@:]+:[^\s@:]+$', line.strip())
                and len(line.strip()) <= 64
            ]
        else:
            filtered = output

        unique_filtered = []
        if leech.use_database and db_cursor:
            # Use database to check for duplicates
            for line in filtered:
                try:
                    db_cursor.execute('INSERT INTO combos (combo) VALUES (?)', (line,))
                    unique_filtered.append(line)
                except sqlite3.IntegrityError:
                    # Combo already exists in database
                    pass
            db_connection.commit()
        else:
            # Do not use database, remove duplicates locally
            unique_filtered = list(set(filtered))

        with scraped_lock:
            scraped += len(unique_filtered)

        # Update total combos in GUI if ComboScraperApp instance exists
        if leech.app_instance and hasattr(leech.app_instance, 'update_total_combos_label'):
            leech.app_instance.update_total_combos_label(scraped)

        print(f"Scraped [{len(unique_filtered)}] from [{thread}] at [{host}]")
        if unique_filtered:
            if not os.path.exists(result_folder):
                os.makedirs(result_folder)
            with open(os.path.join(result_folder, 'scrapedcombos.txt'), 'a', encoding='utf-8') as f:
                f.write('\n'.join(unique_filtered) + "\n")

    @staticmethod
    def gofile(link, thread, content_id=None):
        if stop_event.is_set():
            return
        while pause_event.is_set():
            time.sleep(1)
        if content_id is not None:
            try:
                token_resp = requests.post("https://api.gofile.io/createAccount").json()
                token = token_resp["data"]["token"]
                wt = requests.get("https://gofile.io/dist/js/alljs.js").text.split('wt:"')[1].split('"')[0]
                data = requests.get(
                    f"https://api.gofile.io/getContent?contentId={content_id}&token={token}&websiteToken={wt}&cache=true",
                    headers={"Authorization": "Bearer " + token},
                ).json()
                if data["status"] == "ok":
                    if not data["data"].get("passwordProtected", False):
                        if data["data"]["type"] == "folder":
                            for child in data["data"]["contents"].values():
                                if child["type"] == "folder":
                                    leech.gofile(link, thread, content_id=child["id"])
                                else:
                                    file_link = child["link"]
                                    content = requests.get(file_link).text
                                    leech.save(content, thread, "gofile.io")
                        else:
                            file_link = data["data"]["downloadPage"]
                            content = requests.get(file_link).text
                            leech.save(content, thread, "gofile.io")
            except Exception as e:
                logging.error(f"Error in gofile: {e}", exc_info=True)
        else:
            leech.gofile(link, thread, link.split("/")[-1])

    @staticmethod
    def handle(link, thread):
        if stop_event.is_set():
            return
        while pause_event.is_set():
            time.sleep(1)
        try:
            if link.startswith('https://www.upload.ee/files/'):
                f = BeautifulSoup(requests.get(link, headers=agent).text, 'html.parser')
                download = f.find('a', id='d_l').get('href')
                content = requests.get(download, headers=agent).text
                leech.save(content, thread, "upload.ee")
            elif link.startswith('https://www.mediafire.com/file/'):
                f = BeautifulSoup(requests.get(link, headers=agent).text, 'html.parser')
                download_link = f.find('a', id='downloadButton')
                if download_link:
                    download = download_link.get('href')
                    content = requests.get(download, headers=agent).text
                    leech.save(content, thread, "mediafire.com")
            elif link.startswith('https://pixeldrain.com/u/'):
                content = requests.get(link.replace("/u/", "/api/file/") + "?download", headers=agent).text
                leech.save(content, thread, "pixeldrain.com")
            elif link.startswith('https://mega.nz/file/'):
                # Note: Requires megatools to be installed in the system
                process = subprocess.Popen(
                    f"megatools dl {link} --no-ask-password --print-names",
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    bufsize=1,
                    universal_newlines=True,
                )
                output = process.stdout.readlines()
                process.wait()
                if output:
                    saved = output[-1].strip()
                    if os.path.exists(saved):
                        with open(saved, 'r', encoding='utf-8') as f:
                            content = f.read()
                        leech.save(content, thread, "mega.nz")
                        os.remove(saved)
            elif link.startswith('https://www.sendspace.com/file/'):
                req = requests.get(link, headers=agent)
                soup = BeautifulSoup(req.text, 'html.parser')
                download_link = soup.find('a', {'id': 'download_button'})
                if download_link:
                    download_url = download_link['href']
                    content = requests.get(download_url, verify=False, headers=agent).text
                    leech.save(content, thread, "sendspace.com")
            elif link.startswith('https://gofile.io/d/'):
                leech.gofile(link, thread)
            elif link.startswith('https://anonfiles.com/'):
                # Handle anonfiles.com
                f = BeautifulSoup(requests.get(link, headers=agent).text, 'html.parser')
                download = f.find('a', id='download-url')
                if download:
                    download_url = download.get('href')
                    response = requests.get(download_url, headers=agent, stream=True)
                    temp_file = os.path.join(result_folder, 'temp_download')
                    with open(temp_file, 'wb') as f:
                        shutil.copyfileobj(response.raw, f)
                    leech.extract_and_save(temp_file, result_folder)
                    os.remove(temp_file)
            else:
                # Handle direct content
                pattern = re.compile(r'^[^\s@:]+@[^\s@:]+\.[^\s@:]+:[^\s@:]+$')
                if pattern.search(link):
                    leech.save([link.strip()], thread, "direct", alr=True)
        except Exception as e:
            logging.error(f"Error handling link {link}: {e}", exc_info=True)

    @staticmethod
    def heypass():
        dupe = []
        try:
            for page in range(1, pages + 1):
                if stop_event.is_set():
                    break
                while pause_event.is_set():
                    time.sleep(1)
                req = requests.get(
                    f"https://heypass.net/forums/combo-lists.69/page-{page}?order=post_date&direction=desc",
                    headers=agent,
                )
                soup = BeautifulSoup(req.text, 'html.parser')
                thread_links = soup.find_all('a', class_='structItem-title')
                logging.info(f"Found [{len(thread_links)}] posts from heypass.net")
                for link in thread_links:
                    if stop_event.is_set():
                        break
                    while pause_event.is_set():
                        time.sleep(1)
                    href = link.get('href')
                    if href and "threads" in href:
                        href = href.strip('latest')
                        if href not in dupe:
                            dupe.append(href)
                            thread_url = "https://heypass.net" + href
                            thread_resp = requests.get(thread_url, headers=agent)
                            s = BeautifulSoup(thread_resp.text, 'html.parser')
                            allhref = s.find_all('a', href=True)
                            for lin in allhref:
                                if stop_event.is_set():
                                    break
                                while pause_event.is_set():
                                    time.sleep(1)
                                leech.handle(lin['href'], thread_url)
        except Exception as e:
            logging.error(f"Error in heypass: {e}", exc_info=True)

    @staticmethod
    def nohide():
        dupe = []
        try:
            for page in range(1, pages + 1):
                if stop_event.is_set():
                    break
                while pause_event.is_set():
                    time.sleep(1)
                req = requests.get(
                    f"https://nohide.space/forums/free-email-pass.3/page-{page}?order=post_date&direction=desc",
                    headers=agent,
                )
                soup = BeautifulSoup(req.text, 'html.parser')
                thread_links = soup.find_all('a', class_='structItem-title')
                logging.info(f"Found [{len(thread_links)}] posts from nohide.space")
                for link in thread_links:
                    if stop_event.is_set():
                        break
                    while pause_event.is_set():
                        time.sleep(1)
                    href = link.get('href')
                    if href and "/threads/" in href:
                        href = href.strip('latest').rsplit('page-', 1)[0]
                        if href not in dupe:
                            dupe.append(href)
                            thread_url = "https://nohide.space" + href
                            s = BeautifulSoup(
                                requests.get(thread_url, headers=agent).text, 'html.parser'
                            )
                            for ele in s.find_all('div', class_='bbWrapper'):
                                link_el = ele.find_all('a', href=True)
                                for url in link_el:
                                    if stop_event.is_set():
                                        break
                                    while pause_event.is_set():
                                        time.sleep(1)
                                    leech.handle(url['href'], thread_url)
        except Exception as e:
            logging.error(f"Error in nohide: {e}", exc_info=True)

    @staticmethod
    def nulled():
        dupe = []
        try:
            for page in range(1, pages + 1):
                if stop_event.is_set():
                    break
                while pause_event.is_set():
                    time.sleep(1)
                req = requests.get(
                    f"https://www.nulled.to/forum/74-combolists/page-{page}?sort_by=Z-A",
                    headers=agent,
                )
                soup = BeautifulSoup(req.text, 'html.parser')
                links = soup.find_all('a', class_='topic_title')
                logging.info(f"Found [{len(links)}] posts from nulled.to")
                for link in links:
                    if stop_event.is_set():
                        break
                    while pause_event.is_set():
                        time.sleep(1)
                    href = link.get('href')
                    if href not in dupe:
                        dupe.append(href)
                        s = BeautifulSoup(requests.get(href, headers=agent).text, 'html.parser')
                        post_content = s.find('div', class_='post_body')
                        if post_content:
                            all_links = post_content.find_all('a', href=True)
                            for lnk in all_links:
                                if stop_event.is_set():
                                    break
                                while pause_event.is_set():
                                    time.sleep(1)
                                leech.handle(lnk['href'], href)
        except Exception as e:
            logging.error(f"Error in nulled: {e}", exc_info=True)

    @staticmethod
    def hellofhackers():
        dupe = []
        try:
            for page in range(1, pages + 1):
                if stop_event.is_set():
                    break
                while pause_event.is_set():
                    time.sleep(1)
                req = requests.get(
                    f"https://hellofhackers.com/forums/combolists.18/page-{page}?order=post_date&direction=desc",
                    headers=agent,
                )
                soup = BeautifulSoup(req.text, 'html.parser')
                thread_links = soup.find_all('a', class_='structItem-title')
                logging.info(f"Found [{len(thread_links)}] posts from hellofhackers.com")
                for link in thread_links:
                    if stop_event.is_set():
                        break
                    while pause_event.is_set():
                        time.sleep(1)
                    href = link.get('href')
                    if href and "/threads/" in href:
                        href = href.strip('latest').rsplit('page-', 1)[0]
                        if href not in dupe:
                            dupe.append(href)
                            thread_url = "https://hellofhackers.com" + href
                            s = BeautifulSoup(
                                requests.get(thread_url, headers=agent).text, 'html.parser'
                            )
                            for ele in s.find_all('div', class_='bbWrapper'):
                                link_el = ele.find_all('a', href=True)
                                for url in link_el:
                                    if stop_event.is_set():
                                        break
                                    while pause_event.is_set():
                                        time.sleep(1)
                                    leech.handle(url.get('href'), thread_url)
        except Exception as e:
            logging.error(f"Error in hellofhackers: {e}", exc_info=True)

    @staticmethod
    def crackingx():
        dupe = []
        try:
            for page in range(1, pages + 1):
                if stop_event.is_set():
                    break
                while pause_event.is_set():
                    time.sleep(1)
                req = requests.get(
                    f"https://crackingx.com/forums/5/page-{page}?order=post_date&direction=desc",
                    headers=agent,
                )
                soup = BeautifulSoup(req.text, 'html.parser')
                thread_links = soup.find_all('a', class_='structItem-title')
                logging.info(f"Found [{len(thread_links)}] posts from crackingx.com")
                for link in thread_links:
                    if stop_event.is_set():
                        break
                    while pause_event.is_set():
                        time.sleep(1)
                    href = link.get('href')
                    if href and "/threads/" in href:
                        if href not in dupe:
                            dupe.append(href)
                            thread_url = "https://crackingx.com" + href
                            s = BeautifulSoup(
                                requests.get(thread_url, headers=agent).text, 'html.parser'
                            )
                            for ele in s.find_all('div', class_='bbWrapper'):
                                link_el = ele.find_all('a', href=True)
                                for url in link_el:
                                    if stop_event.is_set():
                                        break
                                    while pause_event.is_set():
                                        time.sleep(1)
                                    leech.handle(url.get('href'), thread_url)
        except Exception as e:
            logging.error(f"Error in crackingx: {e}", exc_info=True)

    @staticmethod
    def leaksro():
        dupe = []
        try:
            for page in range(1, pages + 1):
                if stop_event.is_set():
                    break
                while pause_event.is_set():
                    time.sleep(1)
                req = requests.get(
                    f"https://www.leaks.ro/forum/308-combolists/page/{page}/?sortby=start_date&sortdirection=desc",
                    headers=agent,
                )
                soup = BeautifulSoup(req.text, 'html.parser')
                thread_links = soup.find_all('a', class_='ipsDataItem_title')
                logging.info(f"Found [{len(thread_links)}] posts from leaks.ro")
                for link in thread_links:
                    if stop_event.is_set():
                        break
                    while pause_event.is_set():
                        time.sleep(1)
                    href = link.get('href')
                    if href and "/topic/" in href:
                        if href not in dupe:
                            dupe.append(href)
                            s = BeautifulSoup(requests.get(href, headers=agent).text, 'html.parser')
                            post_content = s.find('div', class_='ipsContained')
                            if post_content:
                                all_links = post_content.find_all('a', href=True)
                                for lnk in all_links:
                                    if stop_event.is_set():
                                        break
                                    while pause_event.is_set():
                                        time.sleep(1)
                                    leech.handle(lnk['href'], href)
        except Exception as e:
            logging.error(f"Error in leaksro: {e}", exc_info=True)

    @staticmethod
    def pastefo():
        try:
            for page in range(1, pages + 1):
                if stop_event.is_set():
                    break
                while pause_event.is_set():
                    time.sleep(1)
                req = requests.get(f"https://paste.fo/recent/{page}")
                soup = BeautifulSoup(req.text, 'html.parser')
                pastes = soup.find_all('tr', class_=False)
                logging.info(f"Found [{len(pastes)}] pastes on paste.fo")
                for paste in pastes:
                    if stop_event.is_set():
                        break
                    while pause_event.is_set():
                        time.sleep(1)
                    links = paste.find_all('a')
                    for link in links:
                        paste_id = link.get('href').split('/')[-1]
                        content = requests.get(f"https://paste.fo/raw/{paste_id}").text
                        data = re.findall(
                            r'^[^\s@:]+@[^\s@:]+\.[^\s@:]+:[^\s@:]+$',
                            content,
                            re.MULTILINE
                        )
                        if data:
                            leech.save(data, f"https://paste.fo/{paste_id}", "paste.fo", alr=True)
        except Exception as e:
            logging.error(f"Error in pastefo: {e}", exc_info=True)

    @staticmethod
    def crackingpro():
        dupe = []
        try:
            for page in range(1, pages + 1):
                if stop_event.is_set():
                    break
                while pause_event.is_set():
                    time.sleep(1)
                req = requests.get(
                    f"https://www.crackingpro.com/forum/23-combos/page/{page}/", headers=agent
                )
                soup = BeautifulSoup(req.text, 'html.parser')
                thread_links = soup.find_all('a', class_='ipsDataItem_title')
                logging.info(f"Found [{len(thread_links)}] posts from crackingpro.com")
                for link in thread_links:
                    if stop_event.is_set():
                        break
                    while pause_event.is_set():
                        time.sleep(1)
                    href = link.get('href')
                    if '/topic/' in href:
                        if href not in dupe:
                            dupe.append(href)
                            s = BeautifulSoup(requests.get(href, headers=agent).text, 'html.parser')
                            post_content = s.find('div', class_='cPost_contentWrap')
                            if post_content:
                                all_links = post_content.find_all('a', href=True)
                                for lnk in all_links:
                                    if stop_event.is_set():
                                        break
                                    while pause_event.is_set():
                                        time.sleep(1)
                                    leech.handle(lnk['href'], href)
        except Exception as e:
            logging.error(f"Error in crackingpro: {e}", exc_info=True)

    @staticmethod
    def combolist():
        dupe = []
        try:
            for page in range(1, pages + 1):
                if stop_event.is_set():
                    break
                while pause_event.is_set():
                    time.sleep(1)
                req = requests.get(
                    f"https://www.combolist.xyz/category/combolist-5?page={page}", headers=agent
                )
                soup = BeautifulSoup(req.text, 'html.parser')
                thread_links = soup.find_all('h3', class_='entry-title')
                logging.info(f"Found [{len(thread_links)}] posts from combolist.xyz")
                for link in thread_links:
                    if stop_event.is_set():
                        break
                    while pause_event.is_set():
                        time.sleep(1)
                    href = link.find('a')['href']
                    if href not in dupe:
                        dupe.append(href)
                        s = BeautifulSoup(requests.get(href, headers=agent).text, 'html.parser')
                        post_content = s.find('div', class_='entry-content')
                        if post_content:
                            all_links = post_content.find_all('a', href=True)
                            for lnk in all_links:
                                if stop_event.is_set():
                                    break
                                while pause_event.is_set():
                                    time.sleep(1)
                                leech.handle(lnk['href'], href)
        except Exception as e:
            logging.error(f"Error in combolist: {e}", exc_info=True)

    @staticmethod
    def anonfiles():
        try:
            SEARCHFOR = ["\"combo\" site:anonfiles.com", "\"Combo\" site:anonfiles.com"]
            DOWNLOADED = os.path.join(result_folder, "downloaded.log")
            DOWNPATH = os.path.join(result_folder, "downloads")
            DESTPATH = os.path.join(result_folder, "inputbreach")

            os.makedirs(DOWNPATH, exist_ok=True)
            os.makedirs(DESTPATH, exist_ok=True)

            done = []
            # Load already downloaded files
            try:
                with open(DOWNLOADED, "r") as f:
                    done = f.read().splitlines()
            except FileNotFoundError:
                pass

            with open(DOWNLOADED, "a+") as f:
                for s in SEARCHFOR:
                    if stop_event.is_set():
                        break
                    while pause_event.is_set():
                        time.sleep(1)
                    query = search(s, stop=10)
                    i = 0
                    for url in query:
                        if stop_event.is_set():
                            break
                        while pause_event.is_set():
                            time.sleep(1)
                        dest = url.split("/")[-1].strip().strip("'")
                        if dest not in done:
                            try:
                                r = requests.get(url, verify=False)
                                html = BeautifulSoup(r.text, "html.parser")
                                down = html.find(id="download-url")
                                if down is None:
                                    continue  # Skip if no download link
                                down_url = down.get("href").strip()
                                down_url = quote(down_url, safe=':/?=&')
                                print(f"Downloading: {down_url}")
                                path = os.path.join(DOWNPATH, f"{i}_{dest}")
                                response = requests.get(down_url, stream=True)
                                with open(path, 'wb') as file:
                                    shutil.copyfileobj(response.raw, file)
                                leech.extract_and_save(path, DESTPATH)
                                os.remove(path)
                                f.write(dest + "\n")
                                f.flush()
                                i += 1
                            except Exception as e:
                                logging.error(f"Error in {url}: {e}", exc_info=True)
                        time.sleep(10)  # Avoid Google ban
        except Exception as e:
            logging.error(f"Error in anonfiles: {e}", exc_info=True)

    @staticmethod
    def extract_and_save(path, dest_folder):
        try:
            if path.lower().endswith(".txt"):
                with open(path, 'r', encoding='utf-8', errors='ignore') as file:
                    content = file.read()
                leech.save(content, thread=path, host="AnonFiles")
            else:
                # Try to extract archive files
                if zipfile.is_zipfile(path):
                    with zipfile.ZipFile(path, 'r') as zip_ref:
                        for member in zip_ref.namelist():
                            if member.lower().endswith(".txt"):
                                with zip_ref.open(member) as file:
                                    content = file.read().decode('utf-8', errors='ignore')
                                    leech.save(content, thread=path, host="AnonFiles")
                elif tarfile.is_tarfile(path):
                    with tarfile.open(path, 'r') as tar_ref:
                        for member in tar_ref.getmembers():
                            if member.isfile() and member.name.lower().endswith(".txt"):
                                file = tar_ref.extractfile(member)
                                content = file.read().decode('utf-8', errors='ignore')
                                leech.save(content, thread=path, host="AnonFiles")
                else:
                    logging.warning(f"Unknown archive format: {path}")
        except Exception as e:
            logging.error(f"Error extracting {path}: {e}", exc_info=True)

    @staticmethod
    def bingscraper():
        try:
            site_list = ['pastebin.com', 'throwbin.com', 'zerobin.net', 'justpaste.it']
            combined_pattern = re.compile(r'^[^\s@:]+@[^\s@:]+\.[^\s@:]+:[^\s@:]+$', re.MULTILINE)
            headers_list = [
                # List of user-agent headers
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko)'
                ' Chrome/91.0.4472.124 Safari/537.36',
                # Add more user agents if needed
            ]
            unique_links = set()
            unique_combos = set()
            # Load keywords
            keywords = leech.load_keywords()
            if not keywords:
                print("No keywords loaded for Bing scraper.")
                return

            total_keywords = len(keywords)
            keywords_processed = 0

            for keyword in keywords:
                if stop_event.is_set():
                    break
                while pause_event.is_set():
                    time.sleep(1)
                for site in site_list:
                    if stop_event.is_set():
                        break
                    while pause_event.is_set():
                        time.sleep(1)
                    url = f'https://www.bing.com/search?q=site:{site} {keyword}'
                    try:
                        req = requests.get(
                            url,
                            headers={'User-Agent': random.choice(headers_list)},
                            timeout=10
                        )
                        req.raise_for_status()
                        links = leech.get_links(req.text)
                        for link in links:
                            if link not in unique_links:
                                unique_links.add(link)
                                # Now extract combos from the link
                                leech.extract_combos_from_link(link, combined_pattern, unique_combos)
                    except Exception as e:
                        logging.error(f"Error fetching data from {url}: {e}", exc_info=True)
                keywords_processed += 1
                print(f"Processed keywords: {keywords_processed}/{total_keywords}")
        except Exception as e:
            logging.error(f"Error in bingscraper: {e}", exc_info=True)

    @staticmethod
    def load_keywords():
        try:
            with open('keywords.txt', 'r', encoding='utf-8', errors='ignore') as f:
                return f.read().splitlines()
        except FileNotFoundError:
            logging.error("Keywords file not found.")
            return []

    @staticmethod
    def get_links(html):
        data = []
        parse_html = BeautifulSoup(html, 'html.parser')
        links = parse_html.find_all('a', href=True)
        exclusions = ["www.netflix.com", "www.bing.com", "microsoft.com", "wikipedia.org",
                      "www.imdb.com", "www.pinterest.com", "www.maps.google", ".pdf",
                      "www.youtube.com", "www.facebook.com", "www.instagram.com",
                      "http://www.google.", "www.paypal.com", "/search?q=",
                      "play.google.com", "steamcommunity.com", "www.reddit.com",
                      "www.amazon.", "business.facebook.com", "facebook.com",
                      "yahoo.com", "msn.com", "tiktok.com"]
        for link in links:
            href = link['href']
            if all(excl not in href for excl in exclusions) and href.startswith("http"):
                data.append(href)
        return data

    @staticmethod
    def extract_combos_from_link(link, pattern, unique_combos):
        if stop_event.is_set():
            return
        while pause_event.is_set():
            time.sleep(1)
        try:
            req = requests.get(link, headers={'User-Agent': agent['User-Agent']}, timeout=10)
            req.raise_for_status()
            combos = pattern.findall(req.text)
            if combos:
                new_combos = set(combos) - unique_combos
                unique_combos.update(new_combos)
                leech.save(list(new_combos), link, "BingScraper", alr=True)
        except Exception as e:
            logging.error(f"Error extracting combos from {link}: {e}", exc_info=True)

class PrintLogger:
    def __init__(self, queue):
        self.queue = queue

    def write(self, message):
        self.queue.put(message)

    def flush(self):
        pass

class ComboScraperApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Combo Scraper                                   [ THIS TOOL IS 100% CREATED BY AI: https://t.me/hofnar05_Worm_GPT ]")
        self.geometry("800x800")
        self.create_widgets()
        self.queue = queue.Queue()
        self.after(100, self.process_queue)
        self.load_settings()
        leech.app_instance = self  # Reference to the app instance for updating total combos

    def create_widgets(self):
        frame = ttk.Frame(self)
        frame.pack(pady=10)

        self.pages_label = ttk.Label(frame, text="Pages to Scrape:")
        self.pages_label.grid(row=0, column=0, sticky='w')

        self.pages_entry = ttk.Entry(frame)
        self.pages_entry.grid(row=0, column=1, sticky='w')
        self.pages_entry.insert(0, "1")  # Default value

        self.use_database_var = tk.BooleanVar(value=True)
        self.use_database_checkbox = ttk.Checkbutton(
            frame, text="Use Database", variable=self.use_database_var)
        self.use_database_checkbox.grid(row=0, column=2, sticky='w', padx=10)

        sites_frame = ttk.LabelFrame(self, text="Select Sites to Scrape")
        sites_frame.pack(fill='both', padx=10, pady=5)

        self.selected_sites = {}
        sites = [
            'heypass',
            'nohide',
            'nulled',
            'hellofhackers',
            'crackingx',
            'leaksro',
            'pastefo',
            'crackingpro',
            'combolist',
            'anonfiles',
            'bingscraper',
        ]
        row = 0
        column = 0
        for site in sites:
            var = tk.BooleanVar()
            chk = ttk.Checkbutton(sites_frame, text=site.capitalize(), variable=var)
            chk.grid(row=row, column=column, sticky='w', padx=5, pady=5)
            self.selected_sites[site] = var
            column += 1
            if column > 2:
                column = 0
                row += 1

        self.passive_scraping_var = tk.BooleanVar()
        self.passive_scraping_checkbox = ttk.Checkbutton(
            self, text="Passive Scraper", variable=self.passive_scraping_var)
        self.passive_scraping_checkbox.pack(pady=5)

        buttons_frame = ttk.Frame(self)
        buttons_frame.pack(pady=10)

        self.start_button = ttk.Button(buttons_frame, text="Start Scraping", command=self.start_scraping)
        self.start_button.grid(row=0, column=0, padx=5)

        self.pause_button = ttk.Button(buttons_frame, text="Pause", command=self.pause_scraping, state='disabled')
        self.pause_button.grid(row=0, column=1, padx=5)

        self.stop_button = ttk.Button(buttons_frame, text="Stop", command=self.stop_scraping, state='disabled')
        self.stop_button.grid(row=0, column=2, padx=5)

        self.total_combos_label = ttk.Label(self, text="Total Combos Found: 0")
        self.total_combos_label.pack(pady=5)

        output_frame = ttk.LabelFrame(self, text="Output")
        output_frame.pack(fill='both', expand=True, padx=10, pady=5)

        self.output_text = tk.Text(output_frame, wrap='word', state='disabled')
        self.output_text.pack(fill='both', expand=True)

    def start_scraping(self):
        global pages
        try:
            pages_input = self.pages_entry.get()
            if not pages_input:
                messagebox.showerror("Error", "Please enter the number of pages to scrape.")
                return
            pages_int = int(pages_input)
            if pages_int <= 0:
                messagebox.showerror("Error", "Please enter a positive integer for pages.")
                return
            else:
                pages = pages_int
        except ValueError:
            messagebox.showerror("Error", "Please enter a valid integer for pages.")
            return

        selected_functions = []
        for site, var in self.selected_sites.items():
            if var.get():
                try:
                    selected_functions.append(getattr(leech, site))
                except AttributeError:
                    messagebox.showerror("Error", f"Scraper for '{site}' not found.")
                    return
        if not selected_functions:
            messagebox.showerror("Error", "Please select at least one site to scrape.")
            return

        leech.use_database = self.use_database_var.get()

        if leech.use_database:
            # Initialize database connection
            global db_connection, db_cursor
            if not os.path.exists('database'):
                os.makedirs('database')
            db_connection = sqlite3.connect(os.path.join('database', 'combos.db'), check_same_thread=False)
            db_cursor = db_connection.cursor()
            db_cursor.execute('CREATE TABLE IF NOT EXISTS combos (combo TEXT PRIMARY KEY)')
        else:
            # Close database if it's open
            if db_connection:
                db_connection.close()
                db_connection = None
                db_cursor = None

        self.pause_button.config(state='normal')
        self.stop_button.config(state='normal')
        threading.Thread(
            target=self.run_scraping, args=(pages, selected_functions), daemon=True
        ).start()
        self.start_button.config(state='disabled')
        self.update_total_combos()

    def run_scraping(self, scrape_pages, functions):
        global scraped
        stop_event.clear()
        pause_event.clear()
        scraped = 0
        print("Starting scraping...")
        sys.stdout = PrintLogger(self.queue)
        try:
            while True:
                if stop_event.is_set():
                    break
                threads = []
                for func in functions:
                    if stop_event.is_set():
                        break
                    while pause_event.is_set():
                        time.sleep(1)
                    thread = threading.Thread(target=func, daemon=True)
                    thread.start()
                    threads.append(thread)
                for thread in threads:
                    thread.join()
                print(f"Scraped [{scraped}] combos from selected sources.")
                if not self.passive_scraping_var.get() or stop_event.is_set():
                    break
                else:
                    print("Passive scraping is on. Restarting scraping...")
                    time.sleep(60)  # Wait before restarting
        except Exception as e:
            logging.error(f"Error in run_scraping: {e}", exc_info=True)
        finally:
            self.start_button.config(state='normal')
            self.pause_button.config(state='disabled')
            self.stop_button.config(state='disabled')
            messagebox.showinfo("Scraping Complete", "Scraping has completed.")

    def update_total_combos(self):
        self.total_combos_label.config(text=f"Total Combos Found: {scraped}")
        if self.pause_button['state'] != 'disabled' or self.stop_button['state'] != 'disabled':
            self.after(1000, self.update_total_combos)  # Update every second

    def update_total_combos_label(self, count):
        self.total_combos_label.config(text=f"Total Combos Found: {count}")

    def pause_scraping(self):
        if not pause_event.is_set():
            pause_event.set()
            self.pause_button.config(text='Resume')
            print("Scraping paused.")
        else:
            pause_event.clear()
            self.pause_button.config(text='Pause')
            print("Scraping resumed.")

    def stop_scraping(self):
        stop_event.set()
        self.start_button.config(state='normal')
        self.pause_button.config(state='disabled')
        self.stop_button.config(state='disabled')
        print("Scraping stopped.")

    def process_queue(self):
        try:
            while not self.queue.empty():
                message = self.queue.get_nowait()
                self.output_text.config(state='normal')
                self.output_text.insert('end', message)
                self.output_text.see('end')
                self.output_text.config(state='disabled')
        except queue.Empty:
            pass
        self.after(100, self.process_queue)

    def save_settings(self):
        data = {
            'pages': self.pages_entry.get(),
            'sites': {site: var.get() for site, var in self.selected_sites.items()},
            'passive_scraping': self.passive_scraping_var.get(),
            'use_database': self.use_database_var.get(),
        }
        with open('settings.pkl', 'wb') as f:
            pickle.dump(data, f)

    def load_settings(self):
        try:
            with open('settings.pkl', 'rb') as f:
                data = pickle.load(f)
                self.pages_entry.insert(0, data.get('pages', '1'))
                for site, var in self.selected_sites.items():
                    var.set(data.get('sites', {}).get(site, False))
                self.passive_scraping_var.set(data.get('passive_scraping', False))
                self.use_database_var.set(data.get('use_database', True))
        except FileNotFoundError:
            pass

    def on_closing(self):
        self.save_settings()
        if db_connection:
            db_connection.close()
        self.destroy()

    def run(self):
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.mainloop()

if __name__ == "__main__":
    app = ComboScraperApp()
    app.run()