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

if (
    not API_KEY
    or not BACKEND_URL
    or not CLIENT_LOG_DIRECTORY
    or not KURO_WAVEPLATE_ENDPOINT
):
    print("One or more env are None")
    exit(1)

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

if not userInfoUrl:
    print("USER_INFO_URL is None")
    exit(1)

userInfoResponse = requests.get(userInfoUrl)
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
    data = response.json()
    if data["code"] == 0:
        playerInfo = data["data"][region]
    elif data["code"] == 1005:
        time.sleep(2)
        continue
    else:
        print("Waveplate endpoint failed")
        exit(1)

if not playerInfo:
    print("Max retries exceeded")
    exit(1)


data = json.loads(playerInfo)

energy = data["Base"]["Energy"]
storeEnergy = data["Base"]["StoreEnergy"]
energyRecoverTimeInMS = data["Base"]["EnergyRecoverTime"]

requests.post(
    BACKEND_URL,
    json={
        "playerId": playerId,
        "region": region,
        "energy": energy,
        "storeEnergy": storeEnergy,
        "energyRecoveryTimeInMS": energyRecoverTimeInMS,
    },
    headers={
        "x-api-key":API_KEY,
        'Content-Type': 'application/json'
    },
)

