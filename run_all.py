#!/usr/bin/env python3
"""
Script completo para VPS Contabo
Extrai dados do Polymarket e envia para GitHub
"""

import requests
import json
import csv
import os
import base64
import subprocess
from datetime import datetime, timezone

# Carregar .env automaticamente se existir
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(ENV_PATH):
    with open(ENV_PATH, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())

# ConfiguraÃ§Ãµes
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN') or os.getenv('PERSONAL_ACCESS_TOKEN')
GITHUB_REPO = os.getenv('GITHUB_REPO', 'aimidas1/Polymarket_price_markets')
DATA_DIR = os.path.dirname(os.path.abspath(__file__))

FIELDS = [
    'snapshot_time', 'competition', 'event', 'market', 'outcome',
    'probability', 'decimal_odds', 'volume', 'volume_24h', 'liquidity',
    'spread', 'end_date', 'market_score', 'url',
    'moneyline', 'total_over_under2.5', 'btts_yes_no'
]

def log(msg):
    try:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    except UnicodeEncodeError:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg.encode('ascii', 'replace').decode('ascii')}")

def prob_to_odds(prob):
    try:
        if prob and float(prob) > 0:
            return round(1.0 / float(prob), 2)
    except:
        pass
    return None

def github_upload(filename, content, message):
    """Upload file to GitHub"""
    if not GITHUB_TOKEN:
        log("ERRO: GITHUB_TOKEN nÃ£o definido!")
        return False
    
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json'
    }
    
    # Check if file exists
    url = f'https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}'
    sha = None
    file_exists = False
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 200:
            sha = resp.json().get('sha')
            file_exists = True
            log(f"  Ficheiro existe, SHA: {sha[:10]}...")
        elif resp.status_code == 404:
            log(f"  Ficheiro novo, a criar...")
        else:
            log(f"  GET status: {resp.status_code}, a tentar criar/atualizar...")
    except Exception as e:
        log(f"  Erro no GET: {e}, a tentar criar...")
    
    # Upload
    b64_content = base64.b64encode(content.encode('utf-8')).decode('utf-8')
    body = {
        'message': message,
        'content': b64_content,
        'branch': 'main'
    }
    if file_exists and sha:
        body['sha'] = sha
    
    try:
        resp = requests.put(url, headers=headers, json=body, timeout=30)
        if resp.status_code in [200, 201]:
            log(f"OK {filename} atualizado no GitHub")
            return True
        else:
            log(f"ERRO a enviar {filename}: {resp.status_code} - {resp.text[:200]}")
            return False
    except Exception as e:
        log(f"ERRO: {e}")
        return False

def extract_leagues():
    """Extract football leagues data"""
    log("A extrair dados das ligas...")
    
    # Read competitions file
    with open(os.path.join(DATA_DIR, 'polymarket_football_competitions.json'), 'r', encoding='utf-8') as f:
        competitions_data = json.load(f)
    
    competitions = competitions_data['competitions']
    snapshot_time = datetime.now(timezone.utc).isoformat()
    all_records = []
    
    for comp_name, comp_info in competitions.items():
        slug = comp_info.get('polymarket_tag_slug')
        if not slug:
            continue
        
        try:
            url = f'https://gamma-api.polymarket.com/events?tag_slug={slug}&active=true&closed=false&limit=500'
            resp = requests.get(url, timeout=30)
            events = resp.json()
            
            games = []
            for event in events:
                tags = [t.get('slug', '') for t in event.get('tags', [])]
                title = event.get('title', '')
                has_games_tag = 'games' in tags
                has_vs = ' vs ' in title.lower() or ' vs. ' in title.lower()
                is_more_markets = 'more markets' in title.lower()
                
                if has_vs and (has_games_tag or is_more_markets):
                    games.append(event)
            
            log(f"  {comp_name}: {len(games)} jogos")
            
            for event in games:
                title = event.get('title', '')
                markets = event.get('markets', [])
                event_url = f"https://polymarket.com/event/{event.get('slug', '')}"
                end_date = event.get('endDate', '')
                
                # Find specific markets
                moneyline_home = None
                moneyline_away = None
                draw = None
                ou_2_5 = None
                btts = None
                
                for market in markets:
                    q = market.get('question', '').lower()
                    outcomes_str = market.get('outcomes', '[]')
                    prices_str = market.get('outcomePrices', '[]')
                    
                    try:
                        outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str
                        prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
                    except:
                        outcomes = []
                        prices = []
                    
                    m_info = {
                        'outcomes': outcomes,
                        'prices': prices,
                        'volume': market.get('volume', ''),
                        'volume_24h': market.get('volume24hr', ''),
                        'liquidity': market.get('liquidity', ''),
                        'spread': market.get('spread', '')
                    }
                    
                    if 'win on' in q and 'draw' not in q:
                        moneyline_home = m_info
                    elif 'draw' in q and 'end in' in q:
                        draw = m_info
                    elif 'o/u 2.5' in q or 'over/under 2.5' in q or ': o/u 2.5' in q:
                        ou_2_5 = m_info
                    elif 'both teams to score' in q:
                        btts = m_info
                    elif 'win on' in q:
                        moneyline_away = m_info
                
                # Helper to create record
                def create_rec(market_type, mkt, idx):
                    prob = mkt['prices'][idx] if idx < len(mkt['prices']) else None
                    return {
                        'snapshot_time': snapshot_time,
                        'competition': comp_name,
                        'event': title,
                        'market': market_type,
                        'outcome': mkt['outcomes'][idx] if idx < len(mkt['outcomes']) else '',
                        'probability': prob,
                        'decimal_odds': prob_to_odds(prob),
                        'volume': mkt['volume'],
                        'volume_24h': mkt['volume_24h'],
                        'liquidity': mkt['liquidity'],
                        'spread': mkt['spread'],
                        'end_date': end_date,
                        'market_score': None,
                        'url': event_url,
                        'moneyline': moneyline_home['prices'][0] if moneyline_home and moneyline_home['prices'] else None,
                        'total_over_under2.5': ou_2_5['prices'][0] if ou_2_5 and ou_2_5['prices'] else None,
                        'btts_yes_no': btts['prices'][0] if btts and btts['prices'] else None
                    }
                
                if moneyline_home:
                    all_records.append(create_rec('moneyline', moneyline_home, 0))
                if draw:
                    all_records.append(create_rec('draw', draw, 0))
                if moneyline_away:
                    all_records.append(create_rec('moneyline', moneyline_away, 0))
                if ou_2_5:
                    for i in range(len(ou_2_5['outcomes'])):
                        all_records.append(create_rec('total_over_under2.5', ou_2_5, i))
                if btts:
                    for i in range(len(btts['outcomes'])):
                        all_records.append(create_rec('btts_yes_no', btts, i))
                        
        except Exception as e:
            log(f"  Erro em {comp_name}: {e}")
    
    # Write CSV
    csv_path = os.path.join(DATA_DIR, 'polymarket_football_odds.csv')
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for rec in all_records:
            writer.writerow({k: rec.get(k, '') for k in FIELDS})
    
    log(f"OK CSV ligas: {len(all_records)} registos")
    return csv_path, len(all_records)

def extract_worldcup():
    """Extract World Cup markets data"""
    log("A extrair dados do World Cup...")
    
    with open(os.path.join(DATA_DIR, 'world_cup_markets_ids.json'), 'r', encoding='utf-8') as f:
        wc_markets = json.load(f)
    
    snapshot_time = datetime.now(timezone.utc).isoformat()
    all_records = []
    
    for market_info in wc_markets:
        slug = market_info['slug']
        try:
            url = f'https://gamma-api.polymarket.com/events?slug={slug}'
            resp = requests.get(url, timeout=30)
            events = resp.json()
            if not events:
                continue
            event = events[0]
            
            title = event.get('title', '').lower()
            markets = event.get('markets', [])
            event_url = f"https://polymarket.com/event/{event.get('slug', '')}"
            end_date = event.get('endDate', '')
            
            for market in markets:
                question = market.get('question', '')
                outcomes_str = market.get('outcomes', '[]')
                prices_str = market.get('outcomePrices', '[]')
                
                try:
                    outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str
                    prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
                except:
                    continue
                
                # Determine market type
                if 'winner' in title and 'top' not in title:
                    mkt_type = 'winner'
                    entity = question.replace('Will ', '').replace(' win the 2026 FIFA World Cup?', '')
                elif 'continent' in title:
                    mkt_type = 'continent_winner'
                    entity = market.get('groupItemTitle', question.replace('Will ', '').replace(' win the 2026 FIFA World Cup?', ''))
                elif 'neymar' in title:
                    mkt_type = 'player_prop'
                    entity = 'Neymar'
                elif 'goalscorer' in title:
                    mkt_type = 'top_goalscorer'
                    entity = question.replace('Will ', '').replace(' win the 2026 FIFA World Cup Top Goalscorer?', '')
                elif 'final' in title or 'reach' in title:
                    mkt_type = 'reach_final'
                    entity = question.replace('Will ', '').replace(' reach the final of the 2026 FIFA World Cup?', '')
                else:
                    mkt_type = 'other'
                    entity = question
                
                for i, outcome in enumerate(outcomes):
                    prob = prices[i] if i < len(prices) else None
                    record = {
                        'snapshot_time': snapshot_time,
                        'competition': 'FIFA World Cup 2026',
                        'event': event.get('title', ''),
                        'market': mkt_type,
                        'outcome': f"{entity} - {outcome}",
                        'probability': prob,
                        'decimal_odds': prob_to_odds(prob),
                        'volume': market.get('volume', ''),
                        'volume_24h': market.get('volume24hr', ''),
                        'liquidity': market.get('liquidity', ''),
                        'spread': market.get('spread', ''),
                        'end_date': end_date,
                        'market_score': None,
                        'url': event_url,
                        'moneyline': None,
                        'total_over_under2.5': None,
                        'btts_yes_no': None
                    }
                    all_records.append(record)
        except Exception as e:
            log(f"  Erro em {slug}: {e}")
    
    # Write CSV
    csv_path = os.path.join(DATA_DIR, 'world_cup_markets_data.csv')
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for rec in all_records:
            writer.writerow({k: rec.get(k, '') for k in FIELDS})
    
    log(f"OK CSV World Cup: {len(all_records)} registos")
    return csv_path, len(all_records)

def main():
    log("Iniciando extraÃ§Ã£o de dados Polymarket")
    log("=" * 50)
    
    # Extract and save leagues
    leagues_csv, leagues_count = extract_leagues()
    
    # Extract and save World Cup
    wc_csv, wc_count = extract_worldcup()
    
    # Upload to GitHub
    log("=" * 50)
    log("A enviar para GitHub...")
    
    with open(leagues_csv, 'r', encoding='utf-8') as f:
        leagues_content = f.read()
    github_upload('polymarket_football_odds.csv', leagues_content, 
                  f"Update football odds - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    with open(wc_csv, 'r', encoding='utf-8') as f:
        wc_content = f.read()
    github_upload('world_cup_markets_data.csv', wc_content,
                  f"Update World Cup markets - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    log("=" * 50)
    log("ConcluÃ­do!")
    log(f"Ligas: {leagues_count} registos")
    log(f"World Cup: {wc_count} registos")

if __name__ == '__main__':
    main()
