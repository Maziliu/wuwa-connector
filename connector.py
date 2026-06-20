#!/usr/bin/env python3
import json
import subprocess
import sys
import threading
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


def log(message: str, title: str = "", isError: bool = False) -> None:
    if not DISCORD_WEBHOOK:
        return
    requests.post(
        DISCORD_WEBHOOK,
        json={
            "embeds": [
                {
                    "title": "Error" if isError else title,
                    "description": message,
                    "color": 0xED4245 if isError else 0x57F287,
                }
            ]
        },
        headers={"Content-Type": "application/json"},
    )


def decodeBytes(rawBytes: bytes) -> bytearray:
    decoded = bytearray(rawBytes)
    for i in range(len(decoded)):
        byte = decoded[i]
        if (byte & 0x0F) % 2 == 1:
            decoded[i] = byte ^ 0xA5
        else:
            decoded[i] = byte ^ 0xEF
    return decoded


def tailForCredentials(
    logPath: str, result: dict, stopEvent: threading.Event, pollInterval: float = 0.25
) -> None:
    playerIdPattern = re.compile(r"SetUserId\s*\[playerId:\s*(\d+)\]")
    oauthCodePattern = re.compile(
        r'"oauthCode"\s*:\s*"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"'
    )
    userInfoUrlPattern = re.compile(
        r'https://gar-service\.aki-game\.net/UserRegion/GetUserInfo\?[^\s\]"]+'
    )

    while not os.path.exists(logPath) and not stopEvent.is_set():
        time.sleep(pollInterval)

    if stopEvent.is_set():
        return

    decodedBuffer = ""

    with open(logPath, "rb") as file:
        while not stopEvent.is_set():
            chunk = file.read()
            if not chunk:
                time.sleep(pollInterval)
                continue

            decodedBuffer += decodeBytes(chunk).decode("utf-8", errors="replace")

            if result.get("playerId") is None:
                match = playerIdPattern.search(decodedBuffer)
                if match:
                    result["playerId"] = match.group(1)
                    log(f"{result['playerId']}", "Found")

            if result.get("oauthCode") is None:
                match = oauthCodePattern.search(decodedBuffer)
                if match:
                    result["oauthCode"] = match.group(1)
                    log(f"{result['oauthCode']}", "Found")

            if result.get("userInfoUrl") is None:
                match = userInfoUrlPattern.search(decodedBuffer.replace("\n", ""))
                if match:
                    result["userInfoUrl"] = match.group(0)
                    log(f"{result['userInfoUrl']}", "Found")

            if all(
                result.get(key) is not None
                for key in ("playerId", "oauthCode", "userInfoUrl")
            ):
                return


try:
    result = {}
    stopEvent = threading.Event()

    tailThread = threading.Thread(
        target=tailForCredentials,
        args=(CLIENT_LOG_DIRECTORY, result, stopEvent),
        daemon=True,
    )
    tailThread.start()

    process = subprocess.Popen(sys.argv[1:])

    tailThread.join(timeout=120)
    stopEvent.set()

    playerId = result.get("playerId")
    oauthCode = result.get("oauthCode")
    userInfoUrl = result.get("userInfoUrl")

    if not playerId:
        log("playerId not found in client log", isError=True)
        process.wait()
        exit(1)
    if not oauthCode:
        log("oauthCode not found in client log", isError=True)
        process.wait()
        exit(1)
    if not userInfoUrl:
        log("userInfoUrl not found in client log", isError=True)
        process.wait()
        exit(1)

    process.wait()

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
    log(formatted, "Inserted")
except Exception as error:
    log(f"Unhandled exception ({type(error).__name__}): {error}", isError=True)
    exit(1)
