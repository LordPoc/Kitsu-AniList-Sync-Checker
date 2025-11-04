import requests
import time
import json

def get_auth_headers(token):
    return {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }

def get_anilist_user_id(username, token):
    query = "query ($userName: String) { User(name: $userName) { id name } }"
    variables = {'userName': username}
    url = 'https://graphql.anilist.co'
    
    try:
        response = requests.post(url, json={'query': query, 'variables': variables}, headers=get_auth_headers(token))
        response.raise_for_status()
        data = response.json()
        
        if 'data' in data and 'User' in data['data'] and data['data']['User']:
            user_id = data['data']['User']['id']
            return user_id
        else:
            return None
    except requests.exceptions.RequestException as e:
        return None

def fetch_anilist_library_map(user_id, token, media_type='MANGA', yield_progress_callback=None):
    """
    Fetches a user's library for a specific media type (MANGA or ANIME).
    """
    query = """
    query ($page: Int, $perPage: Int, $userId: Int, $mediaType: MediaType) {
        Page (page: $page, perPage: $perPage) {
            pageInfo { currentPage, lastPage, hasNextPage }
            mediaList(userId: $userId, type: $mediaType) {
                status
                progress
                media {
                    id
                    siteUrl
                    format
                    synonyms
                    title { romaji, english, native }
                    coverImage { large, medium}
                }
            }
        }
    }
    """
    variables = {
        'userId': user_id,
        'page': 1,
        'perPage': 50,
        'mediaType': media_type.upper() # Ensure it's uppercase (MANGA or ANIME)
    }
    url = 'https://graphql.anilist.co'
    
    anilist_title_map = {}
    entry_count = 0
    
    while True:
        try:
            response = requests.post(url, json={'query': query, 'variables': variables}, headers=get_auth_headers(token))
            response.raise_for_status()
            data = response.json()

            if 'errors' in data:
                break

            page_data = data['data']['Page']
            if 'mediaList' in page_data:
                for entry in page_data['mediaList']:
                    media = entry.get('media')
                    
                    # Filter out novels if we are fetching manga
                    if media_type.upper() == 'MANGA' and media and media.get('format') == 'NOVEL':
                        continue 
                    
                    if not media:
                        continue
                    
                    entry_count += 1
                    
                    entry_data = {
                        'mediaId': media['id'],
                        'status': entry['status'],
                        'progress': entry['progress'],
                        'siteUrl': media.get('siteUrl'),
                        'title': media.get('title', {}),
                        'coverImage': media.get('coverImage', {})
                    }
                    
                    titles_to_add = set()
                    if media.get('title'):
                        if media['title'].get('romaji'): titles_to_add.add(media['title']['romaji'])
                        if media['title'].get('english'): titles_to_add.add(media['title']['english'])
                        if media['title'].get('native'): titles_to_add.add(media['title']['native'])
                    if media.get('synonyms'):
                        titles_to_add.update(media['synonyms'])
                    
                    for title in titles_to_add:
                        anilist_title_map[title] = entry_data

            page_info = page_data['pageInfo']
            
            if yield_progress_callback:
                progress_message = f"Fetched AniList page {page_info['currentPage']} / {page_info['lastPage']}"
                yield_progress_callback(progress_message)

            if not page_info['hasNextPage']: break
            variables['page'] += 1
            time.sleep(1)

        except requests.exceptions.RequestException as e:
            break
            
    return anilist_title_map

def search_anilist_by_title(title, token, media_type='MANGA'):
    """
    Searches AniList for a media item by title and type.
    """
    query = """
    query ($search: String, $page: Int, $perPage: Int, $mediaType: MediaType) {
      Page(page: $page, perPage: $perPage) {
        media(search: $search, type: $mediaType, sort: SEARCH_MATCH) {
          id
          siteUrl
          format
          title { romaji, english }
          coverImage { large, medium }
        }
      }
    }
    """
    variables = {
        'search': title,
        'page': 1,
        'perPage': 5,
        'mediaType': media_type.upper()
    }
    url = 'https://graphql.anilist.co'
    
    try:
        response = requests.post(url, json={'query': query, 'variables': variables}, headers=get_auth_headers(token))
        response.raise_for_status()
        data = response.json()
        
        if 'data' in data and data['data'].get('Page') and data['data']['Page'].get('media'):
            for media in data['data']['Page']['media']:
                # Filter out novels if we are searching for manga
                if media_type.upper() == 'MANGA' and media.get('format') == 'NOVEL':
                    continue
                return media
            return None
        else:
            return None
            
    except requests.exceptions.RequestException:
        return None

def update_anilist_entry_full(media_id, status, progress, token):
    mutation = """
    mutation ($mediaId: Int, $status: MediaListStatus, $progress: Int) {
      SaveMediaListEntry(mediaId: $mediaId, status: $status, progress: $progress) {
        id
        status
        progress
      }
    }
    """
    variables = {
        'mediaId': media_id,
        'status': status,
        'progress': progress
    }
    url = 'https://graphql.anilist.co'
    try:
        response = requests.post(url, json={'query': mutation, 'variables': variables}, headers=get_auth_headers(token))
        response.raise_for_status()
        data = response.json()
        if 'errors' in data:
            return False
        else:
            return True
    except requests.exceptions.RequestException as e:
        return False

def update_anilist_entry_status(media_id, status, token):
    mutation = """
    mutation ($mediaId: Int, $status: MediaListStatus) {
      SaveMediaListEntry(mediaId: $mediaId, status: $status) {
        id
        status
      }
    }
    """
    variables = {
        'mediaId': media_id,
        'status': status,
    }
    url = 'https://graphql.anilist.co'
    try:
        response = requests.post(url, json={'query': mutation, 'variables': variables}, headers=get_auth_headers(token))
        response.raise_for_status()
        data = response.json()
        if 'errors' in data:
            return False
        else:
            return True
    except requests.exceptions.RequestException as e:
        return False
