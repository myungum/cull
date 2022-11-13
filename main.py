import json
import requests
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
import time
from tqdm import tqdm
import matplotlib.pyplot as plt
from datetime import datetime


class ItemStatistics:
    def __init__(self) -> None:
        self.win_cnt = 0
        self.lose_cnt = 0
        self.X = []
        self.Y = []

    def game_end(self, time, win):
        if win:
            self.win_cnt += 1
        else:
            self.lose_cnt += 1
        self.X.append(time)
        self.Y.append(self.get_winning_rate())

    def get_winning_rate(self):
        if (self.win_cnt + self.lose_cnt) == 0:
            return 0
        return 100.0 * self.win_cnt / (self.win_cnt + self.lose_cnt)

    def __repr__(self) -> str:
        return '{}% ({}승 {}패)'.format(self.get_winning_rate(), self.win_cnt, self.lose_cnt)


with open('settings.json', 'r') as file:
    info = dict(json.load(file))
    client = MongoClient(host=info['db_host'], port=info['db_port'])
    db = client[info['db_name']]

MATCH_SAVED = True
MATCH_COUNT = 1000
COUNT_PER_QUERY = 100
DELAY = 1.5  # client can send 50 requests per minute
ITEM_ID = 1083  # cull(수확의 낫)
KEY_PURCHASED = '수확의 낫을 산 경우'
KEY_NOT_PURCHASED = '수확의 낫을 사지 않은 경우'

# 1. get match
if not MATCH_SAVED:
    GET_MATCH_API = 'https://asia.api.riotgames.com/lol/match/v5/matches/by-puuid/{}/ids?start={}&count={}'
    match_id_set = set()
    docs = []
    for i in range(int(MATCH_COUNT / COUNT_PER_QUERY)):
        data = requests.get(url=GET_MATCH_API.format(
            info['puuid'], COUNT_PER_QUERY * i, COUNT_PER_QUERY), headers=info['header']).json()
        for match_id in data:
            match_id_set.add(match_id)
        time.sleep(1.5)
    for match_id in match_id_set:
        try:
            db['match'].insert_one({'matchId': match_id})
        except DuplicateKeyError as e:
            pass

# 2. get game data
GET_GAME_DATA_API = 'https://asia.api.riotgames.com/lol/match/v5/matches/{}'
for doc in tqdm(list(db['match'].find({'game_data': None}))):
    match_id = doc['matchId']
    timeline = requests.get(url=GET_GAME_DATA_API.format(
        match_id), headers=info['header']).json()
    db['match'].update_one({'_id': doc['_id']}, {'$set': {'game_data': timeline}})
    time.sleep(1.5)
    print(doc['_id'])

# 3. get timeline
GET_TIMELINE_API = 'https://asia.api.riotgames.com/lol/match/v5/matches/{}/timeline'
for doc in tqdm(list(db['match'].find({'timeline': None}))):
    match_id = doc['matchId']
    timeline = requests.get(url=GET_TIMELINE_API.format(
        match_id), headers=info['header']).json()
    db['match'].update_one({'_id': doc['_id']}, {'$set': {'timeline': timeline}})
    time.sleep(1.5)
    print(doc['_id'])

# 4. analyze timeline
match_list = list(db['match'].find({}).sort('matchId', 1))[:MATCH_COUNT]
result = dict()
result[KEY_PURCHASED] = ItemStatistics()
result[KEY_NOT_PURCHASED] = ItemStatistics()

for i in tqdm(range(len(match_list))):
    timeline = match_list[i]['timeline']
    game_data = match_list[i]['game_data']
    game_start_timestamp = game_data['info']['gameStartTimestamp']
    game_start_datetime = datetime.fromtimestamp(game_start_timestamp / 1000)

    # 4-1. find user
    pId = -1
    for participant in timeline['info']['participants']:
        if participant['puuid'] == info['puuid']:
            pId = participant['participantId']
            break
    if pId == -1:
        raise Exception('participantId not found')

    # 4-2. trace item
    key = KEY_NOT_PURCHASED
    winning_team = -1
    for frame in timeline['info']['frames']:
        for event in frame['events']:
            if event['type'] == 'ITEM_PURCHASED':
                if event['itemId'] == ITEM_ID and event['participantId'] == pId:
                    key = KEY_PURCHASED
            elif event['type'] == 'GAME_END':
                winning_team = event['winningTeam']
    if winning_team == 100 or winning_team == 200:
        win = (winning_team == 100) ^ (pId > 5)
        result[key].game_end(game_start_datetime, win)

plt.plot(result[KEY_PURCHASED].X, result[KEY_PURCHASED].Y, '-')
plt.plot(result[KEY_NOT_PURCHASED].X, result[KEY_NOT_PURCHASED].Y, '--')
plt.savefig('test.png')
