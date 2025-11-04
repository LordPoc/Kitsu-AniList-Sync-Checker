import os
import time
import json
import re
import unicodedata
from flask import Flask, render_template, Response, stream_with_context, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

from anilist_api import (
    get_anilist_user_id, fetch_anilist_library_map, search_anilist_by_title,
    update_anilist_entry_full, update_anilist_entry_status
)
from kitsu_api import (
    fetch_kitsu_library, get_kitsu_auth_token, get_kitsu_user_id_from_token,
    update_kitsu_entry, translate_anilist_to_kitsu_status,
    search_kitsu_by_title, add_kitsu_entry
)
from audit import compare_and_report

load_dotenv()
ANILIST_USERNAME = os.getenv('ANILIST_USERNAME')
ANILIST_ACCESS_TOKEN = os.getenv('ANILIST_ACCESS_TOKEN')
KITSU_USERNAME = os.getenv('KITSU_USERNAME')
KITSU_PASSWORD = os.getenv('KITSU_PASSWORD')

app = Flask(__name__)
CORS(app) 

latest_report = None
kitsu_token = None
KITSU_USER_ID_MANUAL = None

def _sse_format(message, event_type='log'):
    return f"event: {event_type}\ndata: {json.dumps({'message': message})}\n\n"

def _derive_large_from_anilist_url(url):
    if not url:
        return None
    return url.replace('/cover/small/', '/cover/large/').replace('/cover/medium/', '/cover/large/')

def _pick_anilist_image(cover_dict):
    if not isinstance(cover_dict, dict):
        return None
    return cover_dict.get('large') or cover_dict.get('medium') or _derive_large_from_anilist_url(cover_dict.get('small')) or cover_dict.get('small')

def _normalize_title_for_match(s):
    if not s:
        return None
    cleaned = re.sub(r'[~:;,\-–—\.…·!?"\'\(\)\[\]\{\}\/\\&]', ' ', s)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip().lower()
    return cleaned or None

def _sanitize_search_query(s):
    if not s:
        return None
    q = re.sub(r'[~:;,\-–—\.…·!?"\'\(\)\[\]\{\}\/\\]', ' ', s)
    q = re.sub(r'\s+', ' ', q).strip()
    return q or None

def _normalize_for_dedupe(s):
    if not s:
        return None
    nk = unicodedata.normalize('NFKD', s)
    ascii_only = nk.encode('ascii', 'ignore').decode('ascii')
    cleaned = re.sub(r'[^0-9A-Za-z\s]', ' ', ascii_only)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip().lower()
    return cleaned or None

def run_audit_stream(media_type='MANGA'):
    global latest_report
    global kitsu_token
    global KITSU_USER_ID_MANUAL
    
    if media_type.upper() not in ['MANGA', 'ANIME']:
        media_type = 'MANGA'
    else:
        media_type = media_type.upper()
        
    kitsu_media_type = media_type.lower()
    
    try:
        def yield_log(message):
            yield _sse_format(message)
        
        def yield_progress(current, total, message):
            progress_data = { 'current': current, 'total': total, 'message': message }
            yield f"event: progress\ndata: {json.dumps(progress_data)}\n\n"

        if not ANILIST_ACCESS_TOKEN or len(ANILIST_ACCESS_TOKEN) < 50:
            yield _sse_format("ERROR: Your ANILIST_ACCESS_TOKEN in .env looks incorrect or is missing.", "error")
            return
        
        yield _sse_format(f"--- Starting {media_type.capitalize()} Library Audit ---")

        yield _sse_format("Getting Kitsu token...")
        kitsu_token = get_kitsu_auth_token(KITSU_USERNAME, KITSU_PASSWORD)
        if not kitsu_token:
            yield _sse_format("Halting: Could not get Kitsu access token. Check credentials in .env.", "error")
            return
        yield _sse_format("  -> Kitsu token OK.")

        yield _sse_format("Getting Kitsu User ID...")
        kitsu_id = get_kitsu_user_id_from_token(kitsu_token)
        if not kitsu_id:
            yield _sse_format("Halting: Could not fetch Kitsu User ID.", "error")
            return
        yield _sse_format(f"  -> Found Kitsu User ID: {kitsu_id}")

        yield _sse_format("Getting AniList User ID...")
        anilist_id = get_anilist_user_id(ANILIST_USERNAME, ANILIST_ACCESS_TOKEN)
        if not anilist_id:
            yield _sse_format("Halting: Could not get Anilist User ID. Is your ACCESS_TOKEN valid?", "error")
            return
        yield _sse_format(f"  -> Found AniList User ID: {anilist_id}")
        
        yield _sse_format(f"Fetching AniList {media_type.capitalize()} library (this may take a moment)...")
        anilist_title_map = fetch_anilist_library_map(
            anilist_id, 
            ANILIST_ACCESS_TOKEN,
            media_type=media_type,
            yield_progress_callback=lambda msg: next(yield_log(msg), None)
        )
        anilist_norm_map = {}
        anilist_media_norm_titles = {}
        for raw_title, entry in anilist_title_map.items():
            norm = _normalize_title_for_match(raw_title)
            if not norm:
                continue

            anilist_norm_map.setdefault(norm, entry)
            media_id = entry.get('mediaId')
            if media_id:
                anilist_media_norm_titles.setdefault(media_id, set()).add(norm)
        yield _sse_format("  -> AniList fetch complete.")

        yield _sse_format(f"Fetching Kitsu {media_type.capitalize()} library (this may take a moment)...")
        kitsu_media_list = fetch_kitsu_library(
            kitsu_id, 
            kitsu_token,
            media_type=kitsu_media_type,
            yield_progress_callback=lambda msg: next(yield_log(msg), None)
        )
        if not kitsu_media_list:
            yield _sse_format("Halting: Kitsu library could not be fetched.", "error")
            return
        yield _sse_format("  -> Kitsu fetch complete.")

        anilist_media_map = {entry['mediaId']: entry for entry in anilist_title_map.values()}
        
        reports = {
            'ok': [], 'mismatch_status': [], 'anilist_higher': [], 'kitsu_higher': [],
            'found_on_anilist': [], 
            'not_found_on_anilist': [],
            'found_on_kitsu': [], 
            'not_found_on_kitsu': []
        }
        processed_kitsu_indices = set()
        processed_anilist_media_ids = set()

        total_kitsu_entries = len(kitsu_media_list)
        yield _sse_format(f"--- Comparing Libraries (Pass 1: Kitsu -> AniList)... ---")
        yield _sse_format(f"Found {total_kitsu_entries} Kitsu entries to check.")

        for i, kitsu_entry in enumerate(kitsu_media_list):
            kitsu_title = kitsu_entry.get('canonicalTitle')
            
            yield from yield_progress(
                current=i + 1,
                total=total_kitsu_entries,
                message=f"Checking (1/2): {kitsu_title}"
            )

            match_found = False
            anilist_entry = None
            for title in kitsu_entry.get('titles', []):
                norm = _normalize_title_for_match(title)
                if not norm:
                    continue
                entry = anilist_norm_map.get(norm)
                if entry:
                    anilist_entry = entry
                    match_found = True
                    break
            
            if match_found:
                media_id = anilist_entry['mediaId']
                if media_id not in processed_anilist_media_ids:
                    processed_kitsu_indices.add(i)
                    processed_anilist_media_ids.add(media_id)
                    compare_and_report(
                        kitsu_entry, 
                        anilist_entry, 
                        reports, 
                        kitsu_entry['kitsuUrl'], 
                        anilist_entry['siteUrl']
                    )
            
        yield _sse_format(f"--- Comparing Libraries (Pass 2: AniList -> Kitsu)... ---")
        total_anilist_entries = len(anilist_media_map)
        pass_2_checked = 0
        
        for media_id, anilist_entry in anilist_media_map.items():
            pass_2_checked += 1
            if media_id in processed_anilist_media_ids:
                continue 

            yield from yield_progress(
                current=pass_2_checked,
                total=total_anilist_entries,
                message=f"Checking (2/2): Unmatched AniList item {media_id}"
            )
            
            anilist_titles_set = anilist_media_norm_titles.get(media_id, set())
            
            for i, kitsu_entry in enumerate(kitsu_media_list):
                if i in processed_kitsu_indices:
                    continue 

                kitsu_norm_titles = {_normalize_title_for_match(t) for t in kitsu_entry.get('titles', [])}
                if kitsu_norm_titles & anilist_titles_set:
                    yield _sse_format(f"  -> Found reverse match for AL item: {next(iter(kitsu_norm_titles & anilist_titles_set))}")
                    processed_kitsu_indices.add(i)
                    processed_anilist_media_ids.add(media_id)
                    compare_and_report(
                        kitsu_entry, 
                        anilist_entry, 
                        reports, 
                        kitsu_entry['kitsuUrl'], 
                        anilist_entry['siteUrl']
                    )
                    break 

    
        yield _sse_format("--- Searching for database matches for missing items... ---")
        
        unprocessed_kitsu_items = [k for i, k in enumerate(kitsu_media_list) if i not in processed_kitsu_indices]
        unprocessed_anilist_items = [a for m_id, a in anilist_media_map.items() if m_id not in processed_anilist_media_ids]

        total_search_items = len(unprocessed_kitsu_items) + len(unprocessed_anilist_items)
        current_search_item = 0

        found_on_anilist_ids = set()
        found_on_kitsu_ids = set()

        for kitsu_entry in unprocessed_kitsu_items:
            current_search_item += 1
            k_title = kitsu_entry['canonicalTitle']
            yield from yield_progress(
                current_search_item, 
                total_search_items, 
                f"Searching AniList for: {k_title}"
            )
            
            search_result = None
            for title_to_search in kitsu_entry.get('titles', []):
                 search_q = _sanitize_search_query(title_to_search)
                 if not search_q:
                     continue
                 search_result = search_anilist_by_title(search_q, ANILIST_ACCESS_TOKEN, media_type=media_type)
                 time.sleep(1) # Rate limit
                 if search_result:
                     break
            
            if search_result:
                media_id = search_result.get('id')
                if media_id in anilist_media_map:
                    yield _sse_format(f"  -> SKIP: AniList media {media_id} for {k_title} is already in user library.")
                    processed_anilist_media_ids.add(media_id)
                    continue
                if media_id in found_on_anilist_ids or media_id in processed_anilist_media_ids:
                    yield _sse_format(f"  -> Skipping duplicate AniList DB match for: {k_title}")
                    continue

                yield _sse_format(f"  -> Found AniList DB match for: {k_title}")
                reports['found_on_anilist'].append({
                    'k_title': kitsu_entry.get('canonicalTitle'),
                    'k_url': kitsu_entry.get('kitsuUrl'),
                    'k_image': kitsu_entry.get('kitsuImage', {}).get('large'),
                    'k_status': kitsu_entry.get('status'),
                    'k_progress': kitsu_entry.get('progress'),
                    
                    'a_title': search_result.get('title', {}).get('romaji') or search_result.get('title', {}).get('english'),
                    'a_url': search_result.get('siteUrl'),
                    'a_image': _pick_anilist_image(search_result.get('coverImage', {})),
                    'a_media_id': search_result.get('id')
                })
                found_on_anilist_ids.add(media_id)
            else:
                yield _sse_format(f"  -> No AniList DB match for: {k_title}")
                reports['not_found_on_anilist'].append({
                    'k_title': kitsu_entry.get('canonicalTitle'),
                    'k_url': kitsu_entry.get('kitsuUrl'),
                    'k_image': kitsu_entry.get('kitsuImage', {}).get('large'),
                    'k_status': kitsu_entry.get('status'),
                    'k_progress': kitsu_entry.get('progress'),
                })

        kitsu_media_ids_in_library = {str(k.get('media_id')) for k in kitsu_media_list if k.get('media_id')}
        for anilist_entry in unprocessed_anilist_items:
            current_search_item += 1
            title_obj = anilist_entry.get('title') or {}
            a_title = title_obj.get('romaji') or title_obj.get('english') or title_obj.get('native')
            if not a_title:
                a_title = anilist_entry.get('a_title_romaji') or anilist_entry.get('a_title_english')

            if not a_title:
                yield _sse_format("  -> Skipping AniList item with no usable title.")
                reports['not_found_on_kitsu'].append({
                    'a_title': None,
                    'a_url': anilist_entry.get('siteUrl'),
                    'a_image': _pick_anilist_image(anilist_entry.get('coverImage', {})),
                    'a_status': anilist_entry.get('status'),
                    'a_progress': anilist_entry.get('progress'),
                })
                continue

            yield from yield_progress(
                current_search_item,
                total_search_items,
                f"Searching Kitsu for: {a_title}"
            )

            search_q = _sanitize_search_query(a_title)
            if not search_q:
                search_result = None
            else:
                search_result = search_kitsu_by_title(search_q, kitsu_token, media_type=kitsu_media_type)
                time.sleep(1) # Rate limit

            if search_result:
                k_media_id = search_result.get('id')
                if k_media_id in kitsu_media_ids_in_library:
                    yield _sse_format(f"  -> SKIP: Kitsu media {k_media_id} for {a_title} is already in user library.")
                    continue
                if k_media_id in found_on_kitsu_ids:
                    yield _sse_format(f"  -> Skipping duplicate Kitsu DB match for: {a_title}")
                    continue

                yield _sse_format(f"  -> Found Kitsu DB match for: {a_title}")
                reports['found_on_kitsu'].append({
                    'a_title': a_title,
                    'a_url': anilist_entry.get('siteUrl'),
                    'a_image': _pick_anilist_image(anilist_entry.get('coverImage', {})),
                    'a_status': anilist_entry.get('status'),
                    'a_progress': anilist_entry.get('progress'),
                    
                    'k_title': search_result.get('attributes', {}).get('canonicalTitle'),
                    'k_url': f"https://kitsu.io/{kitsu_media_type}/{search_result.get('attributes', {}).get('slug')}",
                    'k_image': search_result.get('attributes', {}).get('posterImage', {}).get('large'),
                    'k_media_id': search_result.get('id'),
                    'a_media_id': anilist_entry.get('mediaId'),
                    'media_type': kitsu_media_type
                })
                found_on_kitsu_ids.add(k_media_id)
            else:
                yield _sse_format(f"  -> No Kitsu DB match for: {a_title}")
                reports['not_found_on_kitsu'].append({
                    'a_title': a_title,
                    'a_url': anilist_entry.get('siteUrl'),
                    'a_image': _pick_anilist_image(anilist_entry.get('coverImage', {})),
                    'a_status': anilist_entry.get('status'),
                    'a_progress': anilist_entry.get('progress'),
                })

        
        seen_a_ids = set()
        seen_k_ids = set()
        seen_pairs = set()

        def _pair(it):
            return (_normalize_for_dedupe(it.get('k_title') or ''), _normalize_for_dedupe(it.get('a_title') or ''))

        anilist_out = []
        for it in reports['found_on_anilist']:
            a_id = it.get('a_media_id')
            k_id = it.get('k_media_id')
            pair = _pair(it)
            if a_id and a_id in seen_a_ids:
                continue
            if k_id and k_id in seen_k_ids:
                continue
            if pair in seen_pairs:
                continue
            anilist_out.append(it)
            if a_id:
                seen_a_ids.add(a_id)
            if k_id:
                seen_k_ids.add(k_id)
            seen_pairs.add(pair)
        reports['found_on_anilist'] = anilist_out

        kitsu_out = []
        for it in reports['found_on_kitsu']:
            a_id = it.get('a_media_id')
            k_id = it.get('k_media_id')
            pair = _pair(it)

            if a_id and a_id in seen_a_ids:
                continue
            if k_id and k_id in seen_k_ids:
                continue
            if pair in seen_pairs:
                continue
            kitsu_out.append(it)
            if a_id:
                seen_a_ids.add(a_id)
            if k_id:
                seen_k_ids.add(k_id)
            seen_pairs.add(pair)
        reports['found_on_kitsu'] = kitsu_out

        if seen_a_ids:
            reports['not_found_on_kitsu'] = [n for n in reports['not_found_on_kitsu'] if n.get('a_title') and _normalize_for_dedupe(n.get('a_title')) not in {p[1] for p in seen_pairs} and n.get('a_title') not in {it.get('a_title') for it in reports['found_on_anilist']}]
        if seen_k_ids:
            reports['not_found_on_anilist'] = [n for n in reports['not_found_on_anilist'] if n.get('k_title') and _normalize_for_dedupe(n.get('k_title')) not in {p[0] for p in seen_pairs} and n.get('k_title') not in {it.get('k_title') for it in reports['found_on_kitsu']}]

        latest_report = reports
        latest_report['kitsu_user_id'] = kitsu_id
        latest_report['media_type'] = kitsu_media_type
        
        report_summary_data = {
            'kitsu_total': len(kitsu_media_list),
            'anilist_total': len(anilist_media_map),
            'ok': len(reports['ok']),
            'mismatch_status': len(reports['mismatch_status']),
            'anilist_higher': len(reports['anilist_higher']),
            'kitsu_higher': len(reports['kitsu_higher']),
            'found_on_anilist': len(reports['found_on_anilist']),
            'not_found_on_anilist': len(reports['not_found_on_anilist']),
            'found_on_kitsu': len(reports['found_on_kitsu']),
            'not_found_on_kitsu': len(reports['not_found_on_kitsu']),
        }
        
        yield f"event: report\ndata: {json.dumps(report_summary_data)}\n\n"
        yield _sse_format("--- Audit Complete ---")

    except GeneratorExit:
        return
    except Exception as e:
        yield _sse_format(f"An uncaught error occurred: {e}", "error")
        import traceback
        traceback.print_exc()

@app.route('/sync', methods=['POST'])
def sync_entry():
    data = request.json
    sync_target = data.get('target') 
    sync_type = data.get('syncType')
    
    try:
        kitsu_token = None
        if sync_target == 'kitsu': 
            kitsu_token = get_kitsu_auth_token(KITSU_USERNAME, KITSU_PASSWORD)
            if not kitsu_token:
                return jsonify({'success': False, 'message': 'Could not get Kitsu token.'}), 500

        if sync_target == 'anilist':
            a_media_id = data.get('aMediaId') 
            status = data.get('status') 
            progress = data.get('progress') 
            
            if sync_type == 'full':
                success = update_anilist_entry_full(a_media_id, status, progress, ANILIST_ACCESS_TOKEN)
            elif sync_type == 'status': 
                success = update_anilist_entry_status(a_media_id, status, ANILIST_ACCESS_TOKEN)
            elif sync_type == 'add':
                success = update_anilist_entry_full(a_media_id, status, progress, ANILIST_ACCESS_TOKEN)
            else:
                return jsonify({'success': False, 'message': 'Invalid sync_type for anilist.'}), 400
            
            if success:
                return jsonify({'success': True, 'message': 'AniList entry updated.'})
            else:
                return jsonify({'success': False, 'message': 'Failed to update AniList entry.'}), 500

        elif sync_target == 'kitsu':
            status = data.get('status') 
            progress = data.get('progress')
            kitsu_status = translate_anilist_to_kitsu_status(status)

            try:
                if progress is not None and progress != '':
                    progress_val = int(progress)
                else:
                    progress_val = None
            except (ValueError, TypeError):
                return jsonify({'success': False, 'message': 'Invalid progress value; must be an integer.'}), 400

            if sync_type == 'full':
                k_library_id = data.get('kEntryId')
                success = update_kitsu_entry(k_library_id, kitsu_status, progress_val, kitsu_token)
            elif sync_type == 'status':
                k_library_id = data.get('kEntryId')
                success = update_kitsu_entry(k_library_id, kitsu_status, None, kitsu_token)
            elif sync_type == 'add':
                k_media_id = data.get('kMediaId')
                media_type = data.get('mediaType', 'manga')
                
                k_user_id = data.get('kUserId')
                if not k_user_id:
                    k_user_id = get_kitsu_user_id_from_token(kitsu_token)
                    if not k_user_id:
                        return jsonify({'success': False, 'message': 'Could not determine Kitsu user id for add operation.'}), 500

                if not k_media_id:
                    return jsonify({'success': False, 'message': 'Missing kMediaId for add operation.'}), 400

                success = add_kitsu_entry(k_user_id, k_media_id, kitsu_status, progress_val or 0, kitsu_token, media_type=media_type)
            else:
                return jsonify({'success': False, 'message': 'Invalid sync_type for kitsu.'}), 400

            if success:
                return jsonify({'success': True, 'message': 'Kitsu entry updated.'})
            else:
                return jsonify({'success': False, 'message': 'Failed to update Kitsu entry. Check token, media id and user permissions.'}), 500
        
        else:
            return jsonify({'success': False, 'message': 'Invalid sync target or type.'}), 400
            
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500


@app.route('/report')
def report():
    global latest_report
    if not latest_report:
        return render_template('report.html', report={}, anilist_user=ANILIST_USERNAME, kitsu_user=KITSU_USERNAME, media_type='manga')
        
    return render_template('report.html', 
                           report=latest_report, 
                           anilist_user=ANILIST_USERNAME, 
                           kitsu_user=KITSU_USERNAME,
                           media_type=latest_report.get('media_type', 'manga'))

@app.route('/stream-audit')
def stream_audit():
    media_type = request.args.get('type', 'MANGA').upper()
    return Response(stream_with_context(run_audit_stream(media_type=media_type)),
                    content_type='text/event-stream')

@app.route('/')
def index():
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True, threaded=True)
