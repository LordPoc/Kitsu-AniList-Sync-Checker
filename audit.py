import sys
import time

def compare_and_report(kitsu_entry, anilist_entry, reports, k_url, a_url):
    kitsu_title = kitsu_entry['canonicalTitle']

    k_status = kitsu_entry.get('status')
    a_status = anilist_entry.get('status')
    k_progress = kitsu_entry.get('progress')
    a_progress = anilist_entry.get('progress')

    if k_status is None:
        k_status = "PLANNING" 

    status_match = (k_status == a_status)
    progress_match = (k_progress == a_progress)
    
    report_item = {
        'k_title': kitsu_title,
        'k_status': k_status,
        'k_progress': k_progress,
        'k_url': k_url,

        'k_image': kitsu_entry.get('kitsuImage', {}).get('large'),
        'a_title': anilist_entry.get('title', {}).get('romaji') or anilist_entry.get('title', {}).get('english') or "AniList Title",
        'a_status': a_status,
        'a_progress': a_progress,
        'a_url': a_url,
        'a_image': anilist_entry.get('coverImage', {}).get('large'),
        
        'k_library_id': kitsu_entry.get('libraryEntryId'),
        'a_media_id': anilist_entry.get('mediaId')
    }

    if status_match and progress_match:
        reports['ok'].append(report_item)
        
    elif not progress_match:
        if a_progress > k_progress:
            reports['anilist_higher'].append(report_item)
        else:
            reports['kitsu_higher'].append(report_item)
            
    elif progress_match and not status_match:
        reports['mismatch_status'].append(report_item)
