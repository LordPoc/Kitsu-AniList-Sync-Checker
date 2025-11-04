import requests
import time
import json

def get_kitsu_auth_token(username, password):
    url = "https://kitsu.io/api/oauth/token"
    data = {
        'grant_type': 'password',
        'username': username,
        'password': password
    }
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    
    try:
        response = requests.post(url, json=data, headers=headers)
        response.raise_for_status()
        token_data = response.json()
        access_token = token_data.get('access_token')
        
        if access_token:
            return access_token
        else:
            return None
    except requests.exceptions.RequestException as e:
        return None
    
def get_kitsu_user_id_from_token(token):
    url = "https://kitsu.io/api/edge/users"
    params = {
        'filter[self]': 'true'
    }
    headers = get_kitsu_auth_headers(token)
    
    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        if 'data' in data and len(data['data']) > 0:
            user_id = data['data'][0]['id']
            return user_id
        else:
            return None
    except requests.exceptions.RequestException as e:
        return None

def get_kitsu_auth_headers(token):
    return {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.api+json',
        'Content-Type': 'application/vnd.api+json',
    }

def translate_kitsu_status(kitsu_status):
    status_map = {
        'current': 'CURRENT',
        'completed': 'COMPLETED',
        'onHold': 'PAUSED',
        'dropped': 'DROPPED',
        'planned': 'PLANNING'
    }
    return status_map.get(kitsu_status)

def translate_anilist_to_kitsu_status(anilist_status):
    status_map = {
        'CURRENT': 'current',
        'COMPLETED': 'completed',
        'PAUSED': 'onHold',
        'DROPPED': 'dropped',
        'PLANNING': 'planned'
    }
    return status_map.get(anilist_status)


def fetch_kitsu_media_by_id(media_id, media_data_map, token, media_type='manga'):
    try:
        url = f"https://kitsu.io/api/edge/{media_type.lower()}/{media_id}"
        response = requests.get(url, headers=get_kitsu_auth_headers(token)) 
        response.raise_for_status()
        data = response.json()
        
        if 'data' in data:
            item = data['data']
            attr = item.get('attributes', {})
            title_set = set()
            
            canonical = attr.get('canonicalTitle')
            if canonical:
                title_set.add(canonical)
            
            if attr.get('titles'):
                for lang, title in attr['titles'].items():
                    if title: title_set.add(title)
            
            if attr.get('abbreviatedTitles'):
                title_set.update(attr['abbreviatedTitles'])
            
            if attr.get('synonyms'):
                title_set.update(attr['synonyms'])
            
            media_data_map[media_id] = {
                'canonicalTitle': canonical,
                'slug': attr.get('slug'),
                'titles': title_set,
                'posterImage': attr.get('posterImage', {})
            }
            return True
    except requests.exceptions.RequestException as e:
        return False
    return False

def fetch_kitsu_library(user_id, token, media_type='manga', yield_progress_callback=None):
    media_type_lower = media_type.lower()
    base_url = f"https://kitsu.io/api/edge/users/{user_id}/library-entries"
    
    params = {
        'filter[kind]': media_type_lower,
        'filter[status]': 'current,completed,on_hold,dropped,planned',
        'include': media_type_lower,
        'page[limit]': 50
    }
    
    kitsu_media_list = []
    media_data_map = {}
    next_url = base_url
    page_num = 1
    
    auth_headers = get_kitsu_auth_headers(token)

    while next_url:
        try:
            if yield_progress_callback:
                progress_message = f"Fetching Kitsu page {page_num}..."
                yield_progress_callback(progress_message)
            page_num += 1
            
            response = requests.get(next_url, params=params, headers=auth_headers)
            response.raise_for_status()
            data = response.json()
            
            if 'included' in data:
                for item in data['included']:
                    if item['type'] == media_type_lower:
                        item_id = item['id']
                        if item_id not in media_data_map:
                            attr = item.get('attributes', {})
                            title_set = set()
                            
                            canonical = attr.get('canonicalTitle')
                            if canonical:
                                title_set.add(canonical)
                            
                            if attr.get('titles'):
                                for lang, title in attr['titles'].items():
                                    if title: title_set.add(title)
                            
                            if attr.get('abbreviatedTitles'):
                                title_set.update(attr['abbreviatedTitles'])
                            
                            if attr.get('synonyms'):
                                title_set.update(attr['synonyms'])
                            
                            media_data_map[item_id] = {
                                'canonicalTitle': canonical,
                                'slug': attr.get('slug'),
                                'titles': title_set,
                                'posterImage': attr.get('posterImage', {})
                            }

            if 'data' in data:
                for entry in data['data']:
                    if 'relationships' in entry and media_type_lower in entry['relationships'] and entry['relationships'][media_type_lower].get('data'):
                        media_id = entry['relationships'][media_type_lower]['data']['id']
                        
                        if media_id not in media_data_map:
                            if yield_progress_callback:
                                yield_progress_callback(f"  -> Kitsu 'included' data missing. Fetching {media_id} manually...")
                            fetch_kitsu_media_by_id(media_id, media_data_map, token, media_type_lower)
                            time.sleep(1)

                        if media_id in media_data_map:
                            media_info = media_data_map[media_id]
                            kitsu_status = entry['attributes']['status']
                            
                            kitsu_media_list.append({
                                'titles': media_info['titles'],
                                'canonicalTitle': media_info['canonicalTitle'],
                                'kitsuUrl': f"https://kitsu.io/{media_type_lower}/{media_info['slug']}",
                                'media_id': media_id, 
                                'status': translate_kitsu_status(kitsu_status),
                                'progress': entry['attributes']['progress'],
                                'libraryEntryId': entry['id'],
                                'kitsuImage': media_info.get('posterImage') 
                            })
            
            if 'links' in data and 'next' in data['links']:
                next_url = data['links']['next']
                params = {} 
            else:
                next_url = None
                
            time.sleep(1)

        except requests.exceptions.RequestException as e:
            break
            
    return kitsu_media_list

def search_kitsu_by_title(title, token, media_type='manga'):
    media_type_lower = media_type.lower()
    url = f"https://kitsu.io/api/edge/{media_type_lower}"
    params = {
        'filter[text]': title,
        'page[limit]': 5
    }
    headers = get_kitsu_auth_headers(token)
    
    try:
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        if data.get('data') and len(data['data']) > 0:
            for item in data['data']:
                attr = item.get('attributes', {}) or {}
                subtype = (attr.get('subtype') or '').lower()
                
                if media_type_lower == 'manga' and subtype == 'novel':
                    continue
                    
                return {
                    'id': item.get('id'),
                    'attributes': { 
                        'canonicalTitle': attr.get('canonicalTitle'),
                        'slug': attr.get('slug'),
                        'posterImage': attr.get('posterImage', {})
                    }
                }
        return None 
    except requests.exceptions.RequestException as e:
        return None

def add_kitsu_entry(user_id, media_id, status, progress, token, media_type='manga'):
    """
    Creates a new library entry for a user.
    """
    url = "https://kitsu.io/api/edge/library-entries"
    headers = get_kitsu_auth_headers(token)
    
    payload = {
        "data": {
            "type": "libraryEntries",
            "attributes": {
                "status": status,
                "progress": progress
            },
            "relationships": {
                "user": {
                    "data": {
                        "type": "users",
                        "id": user_id
                    }
                },
                "media": {
                    "data": {
                        "type": media_type.lower(),
                        "id": media_id
                    }
                }
            }
        }
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        return False

def update_kitsu_entry(library_entry_id, status, progress, token):
    """
    Updates an existing library entry by its ID.
    Can update status, progress, or both.
    """
    url = f"https://kitsu.io/api/edge/library-entries/{library_entry_id}"
    headers = get_kitsu_auth_headers(token)
    
    attributes = {}
    if status:
        attributes['status'] = status
    if progress is not None:
        attributes['progress'] = progress
        
    if not attributes:
        return False

    payload = {
        "data": {
            "type": "libraryEntries",
            "id": library_entry_id,
            "attributes": attributes
        }
    }
    
    try:
        response = requests.patch(url, json=payload, headers=headers)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        return False
