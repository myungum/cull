import json
import requests
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
import time
from tqdm import tqdm


class ItemStatistics:
    def __init__(self) -> None:
        self.win_cnt = 0
        self.lose_cnt = 0

    def game_end(self, win):
        if win:
            self.win_cnt += 1
        else:
            self.lose_cnt += 1

    def __repr__(self) -> str:
        winning_rate = 100.0 * self.win_cnt / (self.win_cnt + self.lose_cnt)
        return '{}% ({}승 {}패)'.format(winning_rate, self.win_cnt, self.lose_cnt)


with open('settings.json', 'r') as file:
    info = dict(json.load(file))
    client = MongoClient(host=info['db_host'], port=info['db_port'])
    db = client[info['db_name']]

MATCH_SAVED = True
MATCH_COUNT = 300
COUNT_PER_QUERY = 100
DELAY = 1.5  # client can send 50 requests per minute
ITEM_ID = 1083  # cull(수확의 낫)
KEY_PURCHASED = '수확의 낫을 산 경우'
KEY_NOT_PURCHASED = '수확의 낫을 사지 않은 경우'

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
match_list = list(db['match'].find({}).sort('matchId', -1))[:MATCH_COUNT]
result = dict()
result[KEY_PURCHASED] = ItemStatistics()
result[KEY_NOT_PURCHASED] = ItemStatistics()
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
    key = KEY_NOT_PURCHASED
    winningTeam = -1
    for frame in data['info']['frames']:
        for event in frame['events']:
            if event['type'] == 'ITEM_PURCHASED':
                if event['itemId'] == ITEM_ID and event['participantId'] == pId:
                    key = KEY_PURCHASED
            elif event['type'] == 'GAME_END':
                winningTeam = event['winningTeam']
    if winningTeam == 100 or winningTeam == 200:
        win = (winningTeam == 100) ^ (pId > 5)
        result[key].game_end(win)
print(result)
