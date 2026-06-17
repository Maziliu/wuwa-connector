#!/usr/bin/env python3
import json
import subprocess
import sys
from dotenv import load_dotenv
import os
import re
import time
import requests

load_dotenv()
API_KEY = os.getenv("BACKEND_API_KEY")
BACKEND_URL = os.getenv("BACKEND_URL")
CLIENT_LOG_DIRECTORY = os.environ["CLIENT_LOG_DIRECTORY"]
KURO_WAVEPLATE_ENDPOINT = os.getenv("KURO_WAVEPLATE_ENDPOINT")
DISCORD_WEBHOOK = os.getenv("DISCORD_WEBHOOK")
if (
    not API_KEY
    or not BACKEND_URL
    or not CLIENT_LOG_DIRECTORY
    or not KURO_WAVEPLATE_ENDPOINT
    or not DISCORD_WEBHOOK
):
    print("One or more env are None")
    exit(1)


def log(message: str, isError: bool = False) -> None:
    if not DISCORD_WEBHOOK:
        return
    requests.post(
        DISCORD_WEBHOOK,
        json={
            "embeds": [
                {
                    "title": "Error" if isError else "Inserted",
                    "description": message,
                    "color": 0xED4245 if isError else 0x57F287,
                }
            ]
        },
        headers={"Content-Type": "application/json"},
    )


try:
    process = subprocess.Popen(sys.argv[1:])
    process.wait()

    with open(CLIENT_LOG_DIRECTORY, "rb") as file:
        userData = bytearray(file.read())

    for i in range(len(userData)):
        byte = userData[i]
        if (byte & 0x0F) % 2 == 1:
            userData[i] = byte ^ 0xA5
        else:
            userData[i] = byte ^ 0xEF

    content = userData.decode("utf-8", errors="replace")

    playerIdMatch = re.search(r"playerId:\s*(\d+)", content)
    oauthCodeMatch = re.search(r'"oauthCode"\s*:\s*"([^"]+)"', content)
    userInfoUrlMatch = re.search(
        r'https://gar-service\.aki-game\.net/UserRegion/GetUserInfo\?[^\s\]"]+',
        content.replace("\n", ""),
    )

    playerId = playerIdMatch.group(1) if playerIdMatch else None
    oauthCode = oauthCodeMatch.group(1) if oauthCodeMatch else None
    userInfoUrl = userInfoUrlMatch.group(0) if userInfoUrlMatch else None

    if not playerId:
        log("playerId not found in client log", isError=True)
        exit(1)
    if not oauthCode:
        log("oauthCode not found in client log", isError=True)
        exit(1)
    if not userInfoUrl:
        log("userInfoUrl not found in client log", isError=True)
        exit(1)

    userInfoResponse = requests.get(userInfoUrl)
    userInfoResponse.raise_for_status()
    userInfoData = userInfoResponse.json()
    region = userInfoData["UserInfos"][0]["Region"]

    playerInfo = None
    max_retries = 5
    attempts = 0
    while not playerInfo and attempts < max_retries:
        attempts += 1
        response = requests.post(
            KURO_WAVEPLATE_ENDPOINT,
            json={"oauthCode": oauthCode, "playerId": playerId, "region": region},
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()
        data = response.json()
        if data["code"] == 0:
            playerInfo = data["data"][region]
        elif data["code"] == 1005:
            time.sleep(2)
            continue
        else:
            log(f"Waveplate endpoint returned code {data['code']}", isError=True)
            exit(1)

    if not playerInfo:
        log("Max retries exceeded", isError=True)
        exit(1)

    data = json.loads(playerInfo)
    energy = data["Base"]["Energy"]
    storeEnergy = data["Base"]["StoreEnergy"]
    energyRecoverTimeInMS = data["Base"]["EnergyRecoverTime"]

    response = requests.post(
        BACKEND_URL,
        json={
            "playerId": playerId,
            "region": region,
            "energy": energy,
            "storeEnergy": storeEnergy,
            "energyRecoveryTimeInMS": energyRecoverTimeInMS,
        },
        headers={"x-api-key": API_KEY, "Content-Type": "application/json"},
    )
    response.raise_for_status()
    inserted = response.json()

    formatted = json.dumps(inserted, indent=2)
    log(formatted)

except Exception as error:
    log(f"Unhandled exception ({type(error).__name__}): {error}", isError=True)
    exit(1)
