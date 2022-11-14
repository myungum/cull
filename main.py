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
        self.win_list = []

    def append_game_result(self, time, win):
        self.win_list.append((time, win))

    def get_winning_rates(self):
        X = []
        Y = []
        m_dic = dict()
        for time, win in self.win_list:
            time: datetime
            win: bool
            
            m = time.date().replace(day=1)
            if m not in m_dic:
                m_dic[m] = [0, 0]

            if win:
                m_dic[m][0] += 1
            else:
                m_dic[m][1] += 1
        for m, win_lose_cnt in m_dic.items():
            winning_rate = 100.0 * win_lose_cnt[0] / (win_lose_cnt[0] + win_lose_cnt[1])
            X.append(m)
            Y.append(winning_rate)

        return X, Y


with open('settings.json', 'r') as file:
    info = dict(json.load(file))
    client = MongoClient(host=info['db_host'], port=info['db_port'])
    db = client[info['db_name']]

MATCH_SAVED = True
MATCH_COUNT = 1000
COUNT_PER_QUERY = 100
DELAY = 1.5  # client can send 50 requests per minute
MAX_REMAKE_GAME_DURATION = 300
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
        time.sleep(DELAY)
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
    time.sleep(DELAY)
    print(doc['_id'])

# 3. get timeline
GET_TIMELINE_API = 'https://asia.api.riotgames.com/lol/match/v5/matches/{}/timeline'
for doc in tqdm(list(db['match'].find({'timeline': None}))):
    match_id = doc['matchId']
    timeline = requests.get(url=GET_TIMELINE_API.format(
        match_id), headers=info['header']).json()
    db['match'].update_one({'_id': doc['_id']}, {'$set': {'timeline': timeline}})
    time.sleep(DELAY)
    print(doc['_id'])

# 4. analyze timeline
match_list = list(db['match'].find({}).sort('matchId', 1))[:MATCH_COUNT]
result = dict()
result[KEY_PURCHASED] = ItemStatistics()
result[KEY_NOT_PURCHASED] = ItemStatistics()

for i in tqdm(range(len(match_list))):
    timeline = match_list[i]['timeline']
    game_data = match_list[i]['game_data']

    # 다시하기(remake)
    if game_data['info']['gameDuration'] < MAX_REMAKE_GAME_DURATION:
        continue
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
        result[key].append_game_result(game_start_datetime, win)

X, Y = result[KEY_PURCHASED].get_winning_rates()
plt.plot(X, Y, '-')
X, Y = result[KEY_NOT_PURCHASED].get_winning_rates()
plt.plot(X, Y, '--')
plt.savefig('test.png')
