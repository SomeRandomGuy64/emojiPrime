"""Irasutoya: candidate search (in the catalog on the emoji-prime server) and illustration download.

The server keeps Irasutoya's post catalog (titles + image links, refreshed weekly from Irasutoya's public feed).
Illustrations are downloaded only when picked, straight from Irasutoya's image host into the cache.
"""
import os, time

from ep_api import search_many
from ep_common import CACHE, download

__all__ = ["search_many", "fetch_image"]

DIR = os.path.join(CACHE, "irasutoya")


def fetch_image(url):
    dest = os.path.join(DIR, "img", os.path.basename(url.split("?")[0]))
    if not os.path.exists(dest) or os.path.getsize(dest) == 0:
        download(url, dest)
        time.sleep(0.3)
    return dest
