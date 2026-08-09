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

with open("openvortexarchive.yaml", "r") as f:
    Config = yaml.safe_load(stream=f)


database = sqlite3.connect("./openvortexarchive.db")
db_cur   = database.cursor()

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

def templates(string:str, filename:str="", platform:str="", client_type:str="", version:str="", content_disposition:str="", md5:str=""):
    if filename:
        string = string.replace("%<fn>", filename)
    if platform:
        string = string.replace("%<platform>", platform)
    if client_type:
        string = string.replace("%<client_type>", client_type)
    if version:
        string = string.replace("%<version>", version)
    if content_disposition:
        string = string.replace("%<content-disposition>", content_disposition)

    if md5:
        string = string.replace("%<md5>", md5)

    return string

def request_with_tries(url:str) -> tuple[bool, requests.Response | None]:
    print(f" *- Hitting {url}... ")
    tries = Config["retries"]["tries"] + 1
    timeout = Config["retries"]["timeout"]
    request = None
    try:
        while tries > 0:
            request = requests.request(method="GET", url=url, cookies={"session_token": Config["vortex"]["api"]["session_token"]})
            print(f"     *- GO!")

            if request.status_code == 200:
                print(" *- Success")
                return (True, request)
            else:
                tries -= 1
                if tries != 0:
                    print(f"   *- failure {request.status_code}, trying again in {timeout}s")
                    time.sleep(timeout)
                    timeout += Config["retries"]["increment"]

            if tries == 0:
                print(f"   *- giving up")
                return (False, request)
    except Exception:
        print(f"   *- we have failed")
        print(traceback.format_exc())
    except KeyboardInterrupt:
        exit(1)

    return (False, request)

def download_clients(ver:str,app_type:str) -> list[App]:
    # will NOT check if there is an update
    assert app_type == "studio" or app_type == "client", "app_type should be 'studio' or 'client'"
    
    downloaded  = []

    for i in Config["clients"]:
        print(f"Downloading '{ver}' of {app_type} \"{i}\"")

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
                print(f"   *- Filesum {filesum}")

                #start saving it
                print("   *- found, saving")

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
                print(f"   *- we have failed")
                print(traceback.format_exc())
                downloaded.append(App(client_name=i,success=False,code=request.status_code if request else -1,check_time=datetime.datetime.now(datetime.UTC)))
        else:
            downloaded.append(App(client_name=i,success=False,code=request.status_code if request else -1,check_time=datetime.datetime.now(datetime.UTC)))
        
    return downloaded

def describe_db(clients:list[App], ver:str, app_type:str):
    for i in clients:
        db_write(table="archive",
                 values=["success", "code", "client_version", "client_type", "time_checked", "file_md5_sum", "file_last_modified", "file_name", "platform"],
                 data=(i.success,i.code,ver,app_type,i.check_time.timestamp(),i.md5_sum,i.last_modified,i.file_name,i.client_name))

def gen_embed(clients:list[App], ver:str, app_type:str):
    assert app_type == "studio" or app_type == "client", "app_type should be 'studio' or 'client'"
    
    embed = webhook.Embed(f"New Vortex {app_type} {ver}", "")
    embed.author   = webhook.EmbedAuthor(name="openvortexarchive", url="https://github.com")
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
    if type(Config["webhook"]) == str:
        webhook_destination = [Config["webhook"]]
    elif type(Config["webhook"]) == list:
        webhook_destination = Config["webhook"]
    else:
        raise Exception("type of webhook configuration is not a list or string")

    json_embeds = []
    for i in embeds: json_embeds.append(i.to_dict())

    data ={
        "content":   "New update",
        "username":  "openvortexarchive",
        "embeds":    json_embeds
    }

    for i in webhook_destination:
        result = requests.post(url=i, json=data)

        try:
            result.raise_for_status()
        except requests.exceptions.HTTPError as err:
            print(err)
            print(result.content)
        else:
            print(f"Payload delivered successfully, code {result.status_code}.")

def get_latest_versions():
    print("checking versions...")
    versions = {}

    vortex_api = Config["vortex"]["api"]

    for i in ["client", "studio"]:
        url = vortex_api["url"] + vortex_api[i]["version"]

        print(f" *- getting version of {i} from {url}")
        success, request = request_with_tries(url=url)

        if success and request:
            try:
                data = json.loads(request.content.decode())
                assert "version" in data, f"version is not in data ({data})"
                print(f"   *- got {data["version"]}")
                versions[i] = data["version"]
            except Exception as e:
                print(f"   *- we have failed")
                print(traceback.format_exc())
                print(f"   *- giving up on {i}")
                versions[i] = None
        else:
            print(f"   *- giving up on {i}")
            versions[i] = None

    return versions

def check_for_update(app_type:str, version:str):
    print(f"Checking if updated {app_type}...")
    last_version_data = db_read(table="archive_meta", values=["last_version"], where=["client_type"], data=(app_type,))

    if len(last_version_data) == 0:
        print(" *- Is this the first run? No data found")
        db_write(table="archive_meta", values=["last_version","client_type"], data=(version,app_type))
        return True
    
    last_version = last_version_data[0][0]
    
    print(f" *- Saw {last_version} for {app_type}, current is {version}")
    if last_version != version:
        print(f" *- Version is different")
        # record new version 
        db_update(table="archive_meta", values=["last_version"], where=["client_type"],data=(version, app_type))
        return True
    else:
        print(f" *- No update for {app_type}")
        return False




if __name__ == "__main__":
    versions = get_latest_versions()
    assert versions["client"] or versions["server"], "is vortex down? failed to get either version info"

    embeds: list[webhook.Embed] = []

    for i in ["client", "studio"]:
        if versions[i]:
            print(f"! {i} archive:")
            has_update = check_for_update(app_type=i, version=versions[i])

            if has_update:
                print(f"! Has update... updating to {versions[i]}")

                clients = download_clients(ver=versions[i], app_type=i)
                describe_db(clients=clients, ver=versions[i], app_type=i)
                embeds.append(gen_embed(clients=clients,ver=versions[i], app_type=i))


    print("! Done")

    if len(embeds) > 0:
        print("! We have an update chat, sending")
        send_message(embeds=embeds)

