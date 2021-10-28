from typing import Optional
from fastapi import FastAPI, Form, File, UploadFile

from typing import List, Dict
from pprint import pprint

from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from bs4 import BeautifulSoup, Tag

import requests
from http import HTTPStatus
import logging
import os

from ftmap import Topic, FTMap

PALIGO_ASSET_FOLDER = "image"
FTML_DIR = "ftml_files"

app = FastAPI()


@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.get("/ping/")
async def ping() -> dict:
    return {"ping": "pong"}

@app.post("/convert/")
async def convert(fileb: UploadFile = File(...), username: str = Form(...), password: str = Form(...)) -> dict:
    fn = os.path.basename(fileb.filename)
    open('/paligo/' + fn, 'wb').write(fileb.file.read())
    return {
        'username': username,
        'password': password,
        "file_name": fileb.filename,
        "fileb_content_type": fileb.content_type
    }
    return publish_paligo_html5_files()


class FTError(Exception):
    pass


def publish_paligo_html5_files(user: None, password: None, tenant: None, ft_source: None, customer: None, start_dir: None):
    print(user, password, tenant, ft_source, customer, start_dir)
    raise Exception('function entered')

    for folder, toc_file, index_file in find_dir_with_toc(start_dir):
        # 1. find the TOC
        print("working on", toc_file)
        ### identify each element of the TOC
        with toc_file.open() as f:
            soup = BeautifulSoup(f, "lxml")
        topic_list = extract_topics(folder, soup)
        print(len(topic_list), "nodes to add to ftmap")

        # 2. extract metadata from the index.html file
        index_soup = BeautifulSoup(open(index_file), "lxml")
        index_metadata = extract_metadata(index_soup)
        index_metadata["customer"] = customer
        # add the index file as first of topic_list
        index_topic = Topic(
            id=index_metadata["bundle-id"] + "_" + index_file.stem,
            title=index_metadata["ft:title"],
            link=index_file.name,
            metas=index_metadata,
            content=get_topic_content(index_soup),
        )
        topic_list.insert(0, index_topic)

        # 3. for each element of the TOC, add it to the ftmap with the index.html metadata
        ftmap = create_ftmap(
            index_file,
            metadata=index_metadata,
            topic_list=topic_list,
        )

        # 4. zip the content
        ftml_zip = zip_all(folder, ftmap, topic_list)

        # 5. publish it to the FT portal
        do_publish(ftml_zip, tenant, user, password, ft_source, customer)


def do_publish(
    zip: Path, portal_url: str, user: str, passwd: str, source_id: str, customer: str
):
    """Upload and publish an FTML archive to an FT portal."""
    # Prepare FT Session
    logger.debug(f"uploading to {portal_url}")
    ft_session = requests.Session()
    login_url = portal_url + "/api/authentication/login"
    rep = ft_session.post(login_url, json={"login": user, "password": passwd})
    if not rep.ok:
        raise FTError(
            f"Cannot log in to FT portal {login_url} (user={user}, password=XXX): {rep.content}"
        )

    # Verify that the server is reachable and has FTML source exists
    list_sources_url = f"{portal_url}/api/admin/khub/sources"
    r = ft_session.get(list_sources_url)
    if r.status_code in [HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN]:
        raise FTError(f"Server rejected credentials as Unauthorized ({r.status_code}).")
    elif r.status_code == HTTPStatus.NOT_FOUND:
        raise FTError(
            f'The instance id or the API in "{list_sources_url}" is not found ({r.status_code}).'
        )
    elif not rep.ok:
        raise FTError(r.text)

    # Upload FTML zip archive
    zipfile = {"file": (f"{customer}_" + Path(zip).name, zip.open("rb"))}
    post_url = f"{portal_url}/api/admin/khub/sources/{source_id}/upload"
    r = ft_session.post(post_url, files=zipfile)
    if r.status_code == HTTPStatus.OK:
        answer = r.json()
        logger.info(f"{zip} file published on {portal_url}.")
        pprint(answer)
    else:
        raise FTError(r.text)


def zip_all(folder: Path, ftmap: Path, topic_list: list[Topic]) -> Path:
    """
    create an archive with ftmap, html files and assets (no need of javascript or css)
    """
    zip_file = folder / (ftmap.stem + ".zip")
    # logger.debug(f"will zip to {zip_file}")
    with ZipFile(zip_file, mode="w", compression=ZIP_DEFLATED) as archive:
        # add the ftmap
        archive.write(ftmap, arcname=ftmap.relative_to(folder))
        ## add all topics content recursively
        fill_archive_with_topics(archive, topic_list, folder)

        asset_dir = folder / PALIGO_ASSET_FOLDER
        for img in list(asset_dir.glob("*")):
            archive.write(img, arcname=img.relative_to(folder))

    return zip_file


def fill_archive_with_topics(archive: ZipFile, topic_list: list[Topic], folder: Path):
    for topic in topic_list:
        # 1. add topic
        archive.writestr(topic.link, topic.content)
        # 2. add sub_topics
        if topic.sub_topics:
            fill_archive_with_topics(archive, topic.sub_topics, folder)


def extract_metadata(soup):
    """extracts all <meta> name/content key-value pairs"""
    meta_dict = {
        "ft:title": soup.title.text,
    }
    meta_tags = soup.find_all("meta")
    for m in meta_tags:
        if "name" not in m.attrs:
            continue
        key = m["name"]
        value = m["content"]
        if key not in meta_dict:
            meta_dict[key] = value
        else:
            if type(meta_dict[key]) == str:
                meta_dict[key] = [meta_dict[key], value]
            elif type(meta_dict[key]) == list:
                meta_dict[key].append(value)
            else:
                raise (
                    Exception(
                        f"invalid meta_dict[key] type: key={key}, type={type(meta_dict[key])}"
                    )
                )
    return meta_dict


def create_ftmap(index_file: Path, metadata: dict, topic_list: list) -> Path:
    ftmap_file = index_file.parent / f"{metadata['bundle-id']}.ftmap"
    logger.debug(f"create ftmap for index_file as {ftmap_file}")

    ftmap = FTMap(
        title=metadata["ft:title"],
        origin_id=metadata["bundle-id"],
        editorial_type=metadata.get("ft:editorialType", "book"),
        lang=metadata.get("ft:lang", "en-US"),
    )
    ft_metas = {}
    for k, v in metadata.items():
        if k == "title" or k == "bundle_id":
            continue
        ft_metas[k] = v
    ftmap.add_metas(ftmap.root, ft_metas)
    logger.debug(f"FT metas = {ft_metas}")

    collected_files = ftmap.populate_toc_paligo(ftmap.get_toptoc(), None, topic_list)
    logger.debug(f"FTMap collected_files= {collected_files}")

    ftmap.write(ftmap_file)

    return ftmap_file


def extract_topics(
    parent_folder: str,
    soup: BeautifulSoup,
    selector: str = "ul.toc > li > a.topic-link",
    parent: Tag = None,
) -> List:
    """extract topics from Paligo's TOC"""

    topic_list = []
    topics = soup.select(selector)
    # print("###", parent_link, "###", len(topics), "links")
    for a in topics:
        href = a["href"]
        # if the <a> that was found is not directly a grand-child of the <ul>, then ignore the link
        if parent and a.parent.parent != parent:
            print("found a <a> too far from parent", href)
            continue
        # if a['href'] starts with parent_link#<anchor>, no need to add it as it will be automatically added by the html splitter
        if "#" in href:  # len(parent_link) > 0 and href.startswith(parent_link + "#"):
            print("skipping this link as it's an anchor", href)
            continue

        topic = Topic(title=a.text.strip(), link=a["href"], id=a["href"].split(".")[0])
        ul = a.parent.find("ul")
        if ul is not None:
            # if ul has li > a.topic-link elements, recursive add them to topic.sub_topics
            topic.sub_topics = extract_topics(
                parent_folder, ul, "li > a.topic-link", parent=ul
            )

        ## extract metadata from the topic file
        print(topic.link)
        topic_path = parent_folder / topic.link
        topic_soup = BeautifulSoup(open(topic_path), features="lxml")
        topic.metas = extract_metadata(topic_soup)

        ## extract relevant content from topic file
        topic.content = get_topic_content(topic_soup)
        ## append to list of topics
        topic_list.append(topic)
    return topic_list


def get_topic_content(topic_soup: BeautifulSoup) -> str:
    """return the relevant content of a Paligo html file"""
    new_soup = BeautifulSoup("<html></html>")
    relevant_content = topic_soup.select_one("div#topic-content > section")
    # remove <div class="titlepage>
    title_tag = relevant_content.select_one("div.titlepage")
    if title_tag:
        title_tag.extract()

    new_soup.html.append(relevant_content)
    return new_soup.prettify()


def find_dir_with_toc(input: str = "."):
    """paligo exports content in one folder per language, each one with a toc-<lang>.html file"""

    curdir = Path(input)
    for sub_folder in sorted(curdir.iterdir()):
        if not sub_folder.is_dir() or str(sub_folder).startswith("."):
            continue
        ## TOC is located in <lang_folder>/toc-<lang>.html
        if len(sub_folder.name) == 2:
            toc_file = sub_folder / f"toc-{sub_folder.name}.html"
            index_file = sub_folder / f"index-{sub_folder.name}.html"
            if toc_file.exists() and index_file.exists():
                yield sub_folder, toc_file, index_file

