#!/usr/bin/env python3

import datetime
import requests
import yaml
import webhook
import sqlite3
import re
import time
import hashlib
import json
import traceback
from io import BytesIO
import sys

with open("openvortexarchive.yaml", "r") as f:
    Config = yaml.safe_load(stream=f)


database = sqlite3.connect("./openvortexarchive.db")
db_cur   = database.cursor()

def log(msg):
    print(msg)


class App:
    def __init__(self, client_name: str, success: bool, code: int, check_time: datetime.datetime, last_modified: str|None = None, md5_sum: str|None = None, download_url: str|None = None, file_name: str|None = None):
        self.client_name =   client_name
        self.success =       success
        self.code =          code
        self.last_modified = last_modified
        self.md5_sum =       md5_sum
        self.download_url =  download_url
        self.check_time =    check_time
        self.file_name =     file_name

        pass


def db_write(table:str,values:list[str], data: tuple=()):
    assert db_cur, "no cursor"
    db_cur.execute(f"INSERT INTO {table} ({",".join(values)}) VALUES ({",".join(["?" for i in range(len(values))])})", data)
    database.commit()
def db_update(table:str,values:list[str], where:list[str]=[], data: tuple=()):
    assert db_cur, "no cursor"
    db_cur.execute(f"UPDATE {table} SET{",".join([" " + i + "=?" for i in values])}{" WHERE" + " AND ".join([" " + i + "=?" for i in where])}", data)
    database.commit()
def db_delete(table:str, where:list[str]=[]):
    assert db_cur, "no cursor"
    db_cur.execute(f"DELETE FROM {table} {" WHERE" + " AND ".join([" " + i + "=?" for i in where])}")
    database.commit()
def db_read(table:str, values:list[str], where:list[str]=[], data: tuple=()) -> list:
    assert db_cur, "no cursor"
    db_cur.execute(f"SELECT {",".join(values)} FROM {table}{" WHERE" + " AND ".join([" " + i + " = (?)" for i in where]) if len(where) > 0 else ""}", data)
    return db_cur.fetchall()

def templates(string:str, filename:str|None=None, platform:str|None=None, client_type:str|None=None, version:str|None=None, content_disposition:str|None=None, md5:str|None=None):
    templates = {
        "%<fn>":                    filename,
        "%<platform>":              platform,
        "%<client_type>":           client_type,
        "%<version>":               version,
        "%<content-disposition>":   content_disposition,
        "%<md5>":                   md5
    }

    for template_string, data in templates.items():
        if data:
            string = string.replace(template_string, data)

    return string

def request_with_tries(url:str) -> tuple[bool, requests.Response | None]:
    log(f" *- Hitting {url}... ")
    tries = Config["retries"]["tries"] + 1
    timeout = Config["retries"]["timeout"]
    request = None
    while tries > 0:
        try:
            log(f"     *- GO!")
            request = requests.request(method="GET", url=url, cookies={"session_token": Config["vortex"]["api"]["session_token"]})

            request.raise_for_status()

            log(" *- Success")
            return (True, request)
        except requests.HTTPError:
            tries -= 1
            if tries != 0:
                assert not isinstance(request, type(None)), "??? for some reason our raise_for_status did not yield a request"
                
                log(f"   *- failure {request.status_code}, trying again in {timeout}s")
                time.sleep(timeout)
                timeout += Config["retries"]["increment"]
        except KeyboardInterrupt:
            exit(1)
        except Exception:
            # generic error
            log(f"   *- we have failed")
            log(traceback.format_exc())
        finally:
            if tries == 0:
                log(f"   *- giving up")
                return (False, request)


    return (False, request)

def download_clients(ver:str,app_type:str) -> list[App]:
    # will NOT check if there is an update
    assert app_type == "studio" or app_type == "client", "app_type should be 'studio' or 'client'"
    
    downloaded  = []

    for i in Config["destination"]["download"]["platforms"][app_type]:
        log(f"Downloading '{ver}' of {app_type} \"{i}\"")

        url = Config["vortex"]["api"]["url"] + \
            templates(string=Config["vortex"]["api"][app_type]["download_url"],
            version=ver,
            client_type=app_type,
            platform=i
            )

        success, request = request_with_tries(url=url)
        if success and request:
            try:
                # MD5 sum the file
                filesum = hashlib.md5(request.content).hexdigest()
                log(f"   *- Filesum {filesum}")

                #start saving it
                log("   *- found, saving")

                if not "client-disposition" in request.headers:
                    log("   *- no client desposition, making one up")
                    content_disposition = f"{app_type}-{i}"
                else:
                    content_disposition = re.findall(pattern="filename=\"(.+)\"", string=request.headers['content-disposition'])[0]
                

                fname = templates(
                    string=Config["destination"]["saving"]["filename"],
                    platform=i, client_type=app_type, version=ver,
                    md5=filesum, content_disposition=content_disposition
                )
                filepath = templates(
                    string=Config["destination"]["saving"]["path"],
                    filename=fname, platform=i, client_type=app_type, version=ver,
                    md5=filesum, content_disposition=content_disposition
                )


                with open(filepath, "wb") as f:
                    f.write(request.content)


                # determine download url from the filename
                download_url = None

                if Config["destination"]["download"]["enable_downloads"]:
                    download_url = templates(
                        string=Config["destination"]["download"]["url"] + Config["destination"]["download"][app_type],
                        filename=fname, platform=i, client_type=app_type, version=ver,
                        md5=filesum, content_disposition=content_disposition)
                downloaded.append(App(client_name=i,success=True,code=request.status_code,last_modified=request.headers["last-modified"] if "last-modified" in request.headers else None,
                    md5_sum=filesum,download_url=download_url,check_time=datetime.datetime.now(datetime.UTC),file_name=fname))
            except Exception as e:
                log(f"   *- we have failed")
                log(traceback.format_exc())
                downloaded.append(App(client_name=i,success=False,code=request.status_code,check_time=datetime.datetime.now(datetime.UTC)))
        else:
            downloaded.append(App(client_name=i,success=False,code=request.status_code if not request == None else -1,check_time=datetime.datetime.now(datetime.UTC)))
        
    return downloaded

def describe_db(clients:list[App], ver:str, app_type:str):
    for i in clients:
        db_write(table="archive",
                 values=["success", "code", "client_version", "client_type", "time_checked", "file_md5_sum", "file_last_modified", "file_name", "platform"],
                 data=(i.success,i.code,ver,app_type,i.check_time.timestamp(),i.md5_sum,i.last_modified,i.file_name,i.client_name))

def gen_embed(clients:list[App], ver:str, app_type:str):
    assert app_type == "studio" or app_type == "client", "app_type should be 'studio' or 'client'"
    
    embed = webhook.Embed(f"New Vortex {app_type} {ver}", "")
    embed.author   = webhook.EmbedAuthor(name="openvortexarchive", url="https://github.com/Jased-0001/openvortexarchive")
    #embed.url = "https://playvortex.io/download"
    embed.timestamp = datetime.datetime.now(datetime.UTC).isoformat()
    embed.color = 0xff0000

    for i in clients:
        newfield = webhook.EmbedField(
            name=i.client_name,
            value="",
            inline=True
        )

        if i.success:
            if i.md5_sum:
                newfield.value += f"MD5 sum: {i.md5_sum}\n"
            if i.last_modified:
                newfield.value += f"Last Modified: {i.last_modified}\n"
            if i.download_url:
                newfield.value += f"[Download]({i.download_url})\n"
        else:
            newfield.value += f"(couldn't download client ({i.code})"

        embed.fields.append(newfield)
        

    return embed

def send_message(embeds: list[webhook.Embed]):
    if type(Config["webhook"]["urls"]) == str:
        webhook_destination = [Config["webhook"]["urls"]]
    elif type(Config["webhook"]["urls"]) == list:
        webhook_destination = Config["webhook"]["urls"]
    else:
        raise Exception("type of webhook configuration is not a list or string")

    json_embeds = []
    for i in embeds: json_embeds.append(i.to_dict())

    data ={
        "content":   Config["webhook"]["content"],
        "username":  "openvortexarchive",
        "embeds":    json_embeds
    }

    for i in webhook_destination:
        result = requests.post(url=i, json=data)

        try:
            result.raise_for_status()
        except requests.exceptions.HTTPError as err:
            log(err)
            log(result.content)
        else:
            log(f"Payload delivered successfully, code {result.status_code}.")

def get_latest_versions():
    log("checking versions...")
    versions = {}

    vortex_api = Config["vortex"]["api"]

    for i in ["client", "studio"]:
        url = vortex_api["url"] + vortex_api[i]["version"]

        log(f" *- getting version of {i} from {url}")
        success, request = request_with_tries(url=url)

        if success and request:
            try:
                data = json.loads(request.content.decode())
                assert "version" in data, f"version is not in data ({data})"
                log(f"   *- got {data["version"]}")
                versions[i] = data["version"]
            except Exception as e:
                log(f"   *- we have failed")
                log(traceback.format_exc())
                log(f"   *- giving up on {i}")
                versions[i] = None
        else:
            log(f"   *- giving up on {i}")
            versions[i] = None

    return versions

def check_for_update(app_type:str, version:str) -> tuple[bool, bool]:
    """Returns (has update bool, is first download bool)"""
    log(f"Checking if updated {app_type}...")
    last_version_data = db_read(table="archive_meta", values=["last_version"], where=["client_type"], data=(app_type,))

    if len(last_version_data) == 0:
        log(" *- Is this the first run? No data found")
        return True, True
    
    last_version = last_version_data[0][0]
    
    log(f" *- Saw {last_version} for {app_type}, current is {version}")
    if last_version != version:
        log(f" *- Version is different")
        return True, False
    else:
        log(f" *- No update for {app_type}")
        return False, False

def write_new_version(app_type:str, version:str, update:bool):
    if update:
        db_update(table="archive_meta", values=["last_version"], where=["client_type"],data=(version, app_type))
    else:
        db_write(table="archive_meta", values=["last_version","client_type"], data=(version,app_type))



if __name__ == "__main__":
    """
    ./main.py <update, meta_clear, db_setup>
    update     - checks for update and runs (no arguments will also run this)
    meta_clear - clears meta database which contains version numbers
    db_setup   - sets up database
    meta_get   - returns json archive_meta
    """

    run_up =     len(sys.argv) == 1 or "update"     in sys.argv
    clear_meta =                           "meta_clear" in sys.argv
    db_setup =                             "db_setup"   in sys.argv
    meta_get =                             "meta_get"   in sys.argv

    db_structure = {
        "archive": """CREATE TABLE "archive" (
	"success"	INTEGER NOT NULL,
	"code"	INTEGER NOT NULL,
	"client_version"	TEXT NOT NULL,
	"client_type"	TEXT NOT NULL,
	"platform"	TEXT NOT NULL,
	"time_checked"	TEXT NOT NULL,
	"file_md5_sum"	TEXT,
	"file_last_modified"	TEXT,
	"file_name"	TEXT
);""",
        "archive_meta": """CREATE TABLE "archive_meta" (
	"client_type"	TEXT NOT NULL,
	"last_version"	TEXT NOT NULL
);"""
    }
    
    if run_up:
        versions = get_latest_versions()
        assert versions["client"] or versions["server"], "is vortex down? failed to get either version info"

        embeds: list[webhook.Embed] = []

        for i in ["client", "studio"]:
            if versions[i]:
                log(f"! {i} archive:")
                has_update, first_download = check_for_update(app_type=i, version=versions[i])

                if has_update:
                    log(f"! Has update... updating to {versions[i]}")

                    clients = download_clients(ver=versions[i], app_type=i)
                    describe_db(clients=clients, ver=versions[i], app_type=i)

                    # we should check if we actually DOWNLOADED anything to update our ver strings
                    for client in clients: 
                        if client.success:
                            log("! we did actually successfully get a client")
                            write_new_version(app_type=i, version=versions[i], update=not first_download)
                            break

                    embeds.append(gen_embed(clients=clients,ver=versions[i], app_type=i))

        if len(embeds) > 0:
            log("! We have an update, sending")
            send_message(embeds=embeds)
    elif clear_meta:
        log("! clearing archive meta")
        assert db_cur, "no cursor"
        db_cur.execute(f"DROP TABLE archive_meta;")
        database.commit()
        db_cur.execute(db_structure["archive_meta"])
        database.commit()
    elif db_setup:
        log("! creating tables")
        assert db_cur, "no cursor"
        for a,b in db_structure.items():
            log(f" *- {a}")
            db_cur.execute(b)
            database.commit()
    elif meta_get:
        data = db_read(table="archive_meta", values=["client_type", "last_version"])
        json_data = {}
        for i in data:
            json_data[i[0]] = i[1]
        print(json.dumps(json_data), end="")