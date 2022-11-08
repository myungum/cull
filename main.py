import json
import requests
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
import time
from tqdm import tqdm


with open('settings.json', 'r') as file:
    info = dict(json.load(file))
    client = MongoClient(host=info['db_host'], port=info['db_port'])
    db = client[info['db_name']]

MATCH_SAVED = True
MATCH_COUNT = 1000
COUNT_PER_QUERY = 100
DELAY = 1.5  # client can send 50 requests per minute
ITEM_ID = 1083  # cull(수확의 낫)

# 1. get match
if not MATCH_SAVED:
    GET_MATCH_API = 'https://asia.api.riotgames.com/lol/match/v5/matches/by-puuid/{}/ids?start={}&count={}'
    matchIdSet = set()
    docs = []
    for i in range(int(MATCH_COUNT / COUNT_PER_QUERY)):
        data = requests.get(url=GET_MATCH_API.format(
            info['puuid'], COUNT_PER_QUERY * i, COUNT_PER_QUERY), headers=info['header']).json()
        for matchId in data:
            matchIdSet.add(matchId)
        time.sleep(1.5)
    for matchId in matchIdSet:
        try:
            db['match'].insert_one({'matchId': matchId})
        except DuplicateKeyError as e:
            pass

# 2. get timeline
GET_TIMELINE_API = 'https://asia.api.riotgames.com/lol/match/v5/matches/{}/timeline'
for doc in tqdm(list(db['match'].find({'data': None}))):
    matchId = doc['matchId']
    data = requests.get(url=GET_TIMELINE_API.format(
        matchId), headers=info['header']).json()
    db['match'].update_one({'_id': doc['_id']}, {'$set': {'data': data}})
    time.sleep(1.5)
    print(doc['_id'])

# 3. analyze timeline
match_list = list(db['match'].find({}))
result = dict()
result[True] = [0, 0]
result[False] = [0, 0]
for doc in tqdm(match_list):
    data = doc['data']

    # 3-1. find user
    pId = -1
    for participant in data['info']['participants']:
        if participant['puuid'] == info['puuid']:
            pId = participant['participantId']
            break
    if pId == -1:
        raise Exception('participantId not found')

    # 3-2. trace item
    itemFound = False

    winningTeam = -1
    for frame in data['info']['frames']:
        for event in frame['events']:
            if event['type'] == 'ITEM_PURCHASED':
                if event['itemId'] == ITEM_ID and event['participantId'] == pId:
                    itemFound = True
            elif event['type'] == 'GAME_END':
                winningTeam = event['winningTeam']
    if winningTeam == 100 or winningTeam == 200:
        win = (winningTeam == 100) ^ (pId > 5)
        if win:
            result[itemFound][0] += 1
        else:
            result[itemFound][1] += 1
print(result)
