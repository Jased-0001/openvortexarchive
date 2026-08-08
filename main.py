import datetime
import requests
import yaml
import webhook
import sqlite3
import re
import time
import hashlib
import json
from io import BytesIO

with open("openvortexarchive.yaml", "r") as f:
    Config = yaml.safe_load(stream=f)


database = sqlite3.connect("./openvortexarchive.db")
db_cur   = database.cursor()


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


def templates(string:str, filename:str=""):
    if filename:
        string = string.replace("%fn", filename)

    return string

def download_clients(ver:str,app_type:str):
    # will NOT check if there is an update
    assert app_type == "studio" or app_type == "client", "app_type should be 'studio' or 'client'"
    
    client_list = Config["vortex"]["api"][app_type]
    downloaded  = []

    for i in client_list["download_urls"]:
        print(f"Downloading '{ver}' of {app_type} \"{i[0]}\"")
        url = Config["vortex"]["api"]["url"] + i[1]
        print(f" *- Hitting {url}... ")

        try:
            tries = 3
            timeout = 10
            while tries > 0:
                request = requests.request(method="GET", url=url, cookies={"session_token": Config["vortex"]["api"]["session_token"]})

                if request.status_code == 200:
                    # MD5 sum the file
                    filesum = hashlib.md5(request.content).hexdigest()
                    print(f"   *- Filesum {filesum}")

                    #start saving it
                    print("   *- found, saving")
                    filepath = f"archive/{app_type}/{i[0]}/"
                    fname = f"{filesum}.{app_type}.{ver}.{re.findall(pattern="filename=\"(.+)\"", string=request.headers['content-disposition'])[0]}"
                    filepath += fname

                    # determine download url from the filename
                    download_url = None

                    if Config["destination"]["enable_downloads"]:
                        # find client in list
                        for x in Config["destination"][app_type]:
                            if x[0] == i[0]:
                                download_url = templates(string=Config["destination"]["url"] + x[1], filename=fname)
                                break

                    with open(filepath, "wb") as f:
                        f.write(request.content)

                    downloaded.append(
                    {
                        "client-name":   i[0],
                        "success":       True,
                        "code":          request.status_code,
                        "last-modified": request.headers["last-modified"] if "last-modified" in request.headers else None,
                        "md5-sum":       filesum,
                        "download-url":  download_url,
                        "check-time":    datetime.datetime.now(datetime.UTC),
                        "file-name":     fname
                    })

                    tries = -999
                else:
                    print(f"   *- failure {request.status_code}, trying again in {timeout}s")
                    tries -= 1
                    time.sleep(timeout)
                    timeout += 10

                if tries == 0:
                    print(f"   *- giving up on {i[0]}")
                    downloaded.append(
                    {
                        "client-name":   i[0],
                        "success":       False,
                        "code":          request.status_code,
                        "last-modified": None,
                        "md5-sum":       None,
                        "download-url":  None,
                        "check-time":    datetime.datetime.now(datetime.UTC),
                        "file-name":     None
                    })
        except Exception as e:
            raise e
        
    return downloaded

def describe_db(clients:list[dict], ver:str, app_type:str):
    for i in clients:
        db_write(table="archive",
                 values=["success", "code", "client_version", "client_type", "time_checked", "file_md5_sum", "file_last_modified", "file_name"],
                 data=(i["success"],i["code"],ver,app_type,i["check-time"].timestamp(),i["md5-sum"],i["last-modified"],i["file-name"]))

def gen_embed(clients:list[dict], ver:str, app_type:str):
    assert app_type == "studio" or app_type == "client", "app_type should be 'studio' or 'client'"
    
    embed = webhook.Embed(f"New Vortex {app_type} {ver}", "")
    embed.author   = webhook.EmbedAuthor(name="openvortexarchive", url="https://github.com")
    #embed.url = "https://playvortex.io/download"
    embed.timestamp = datetime.datetime.now(datetime.UTC).isoformat()
    embed.color = 0xff0000

    for i in clients:
        newfield = webhook.EmbedField(
            name=i["client-name"],
            value="",
            inline=True
        )

        if i["success"]:
            if "md5-sum" in i:
                if i["md5-sum"]:
                    newfield.value += f"MD5 sum: {i["md5-sum"]}\n"
            if "last-modified" in i:
                if i["last-modified"]:
                    newfield.value += f"Last Modified: {i["last-modified"]}\n"
            if "download-url" in i:
                if i["download-url"]:
                    newfield.value += f"[Download]({i["download-url"]})\n"
        else:
            newfield.value += f"(couldn't download client{f", {i["code"]}" if "code" in i else ""})"

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

        try:
            tries = 3
            timeout = 10
            while tries > 0:
                print(f" *- getting version of {i} from {url}")
                request = requests.request(method="GET", url=url, cookies={"session_token": vortex_api["session_token"]})

                if request.status_code == 200:
                    data = json.loads(request.content.decode())
                    assert "version" in data, f"version is not in data ({data})"
                    print(f"   *- got {data["version"]}")
                    versions[i] = data["version"]
                    tries = -999
                else:
                    print(f"   *- failure {request.status_code}, trying again in {timeout}s")
                    tries -= 1
                    time.sleep(timeout)
                    timeout += 10

                if tries == 0:
                    print(f"   *- giving up on {i}")
        except Exception as e:
            raise e
        
    return versions

if __name__ == "__main__":
    versions = get_latest_versions()

    clients = download_clients(ver=versions["client"], app_type="client")
    studio  = download_clients(ver=versions["studio"], app_type="studio")

    describe_db(clients=clients, ver=versions["client"], app_type="client")
    describe_db(clients=studio,  ver=versions["studio"], app_type="studio")

    send_message(embeds=[
        gen_embed(clients=clients,ver=versions["client"], app_type="client"),
        gen_embed(clients=studio,ver=versions["studio"], app_type="studio")
    ])