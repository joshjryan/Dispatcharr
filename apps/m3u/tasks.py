# apps/m3u/tasks.py
import logging
import re
import requests
import os
import gc
import gzip, zipfile
from celery.app.control import Inspect
from celery.result import AsyncResult
from celery import shared_task, current_app, group
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from .models import M3UAccount
from apps.channels.models import Stream, ChannelGroup, ChannelGroupM3UAccount
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.utils import timezone
import time
import json
from core.utils import RedisClient, acquire_task_lock, release_task_lock, natural_sort_key
from core.models import CoreSettings, UserAgent
from asgiref.sync import async_to_sync
from core.xtream_codes import Client as XCClient
from core.utils import send_websocket_update

logger = logging.getLogger(__name__)

BATCH_SIZE = 1000
m3u_dir = os.path.join(settings.MEDIA_ROOT, "cached_m3u")

def fetch_m3u_lines(account, use_cache=False):
    os.makedirs(m3u_dir, exist_ok=True)
    file_path = os.path.join(m3u_dir, f"{account.id}.m3u")

    """Fetch M3U file lines efficiently."""
    if account.server_url:
        if not use_cache or not os.path.exists(file_path):
            try:
                # Try to get account-specific user agent first
                user_agent_obj = account.get_user_agent()
                user_agent = user_agent_obj.user_agent if user_agent_obj else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

                logger.debug(f"Using user agent: {user_agent} for M3U account: {account.name}")
                headers = {"User-Agent": user_agent}
                logger.info(f"Fetching from URL {account.server_url}")

                # Set account status to FETCHING before starting download
                account.status = M3UAccount.Status.FETCHING
                account.last_message = "Starting download..."
                account.save(update_fields=['status', 'last_message'])

                response = requests.get(account.server_url, headers=headers, stream=True)
                response.raise_for_status()

                total_size = int(response.headers.get('Content-Length', 0))
                downloaded = 0
                start_time = time.time()
                last_update_time = start_time
                progress = 0

                with open(file_path, 'wb') as file:
                    send_m3u_update(account.id, "downloading", 0)
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            file.write(chunk)

                            downloaded += len(chunk)
                            elapsed_time = time.time() - start_time

                            # Calculate download speed in KB/s
                            speed = downloaded / elapsed_time / 1024  # in KB/s

                            # Calculate progress percentage
                            if total_size and total_size > 0:
                                progress = (downloaded / total_size) * 100

                            # Time remaining (in seconds)
                            time_remaining = (total_size - downloaded) / (speed * 1024) if speed > 0 else 0

                            current_time = time.time()
                            if current_time - last_update_time >= 0.5:
                                last_update_time = current_time
                                if progress > 0:
                                    # Update the account's last_message with detailed progress info
                                    progress_msg = f"Downloading: {progress:.1f}% - {speed:.1f} KB/s - {time_remaining:.1f}s remaining"
                                    account.last_message = progress_msg
                                    account.save(update_fields=['last_message'])

                                    send_m3u_update(account.id, "downloading", progress,
                                                   speed=speed,
                                                   elapsed_time=elapsed_time,
                                                   time_remaining=time_remaining,
                                                   message=progress_msg)

                # Final update with 100% progress
                final_msg = f"Download complete. Size: {total_size/1024/1024:.2f} MB, Time: {time.time() - start_time:.1f}s"
                account.last_message = final_msg
                account.save(update_fields=['last_message'])
                send_m3u_update(account.id, "downloading", 100, message=final_msg)
            except Exception as e:
                logger.error(f"Error fetching M3U from URL {account.server_url}: {e}")
                # Update account status and send error notification
                account.status = M3UAccount.Status.ERROR
                account.last_message = f"Error downloading M3U file: {str(e)}"
                account.save(update_fields=['status', 'last_message'])
                send_m3u_update(account.id, "downloading", 100, status="error", error=f"Error downloading M3U file: {str(e)}")
                return [], False  # Return empty list and False for success

        # Check if the file exists and is not empty
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            error_msg = f"M3U file not found or empty: {file_path}"
            logger.error(error_msg)
            account.status = M3UAccount.Status.ERROR
            account.last_message = error_msg
            account.save(update_fields=['status', 'last_message'])
            send_m3u_update(account.id, "downloading", 100, status="error", error=error_msg)
            return [], False  # Return empty list and False for success

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.readlines(), True
        except Exception as e:
            error_msg = f"Error reading M3U file: {str(e)}"
            logger.error(error_msg)
            account.status = M3UAccount.Status.ERROR
            account.last_message = error_msg
            account.save(update_fields=['status', 'last_message'])
            send_m3u_update(account.id, "downloading", 100, status="error", error=error_msg)
            return [], False

    elif account.file_path:
        try:
            if account.file_path.endswith('.gz'):
                with gzip.open(account.file_path, 'rt', encoding='utf-8') as f:
                    return f.readlines(), True

            elif account.file_path.endswith('.zip'):
                with zipfile.ZipFile(account.file_path, 'r') as zip_file:
                    for name in zip_file.namelist():
                        if name.endswith('.m3u'):
                            with zip_file.open(name) as f:
                                return [line.decode('utf-8') for line in f.readlines()], True

                    error_msg = f"No .m3u file found in ZIP archive: {account.file_path}"
                    logger.warning(error_msg)
                    account.status = M3UAccount.Status.ERROR
                    account.last_message = error_msg
                    account.save(update_fields=['status', 'last_message'])
                    send_m3u_update(account.id, "downloading", 100, status="error", error=error_msg)
                    return [], False

            else:
                with open(account.file_path, 'r', encoding='utf-8') as f:
                    return f.readlines(), True

        except (IOError, OSError, zipfile.BadZipFile, gzip.BadGzipFile) as e:
            error_msg = f"Error opening file {account.file_path}: {e}"
            logger.error(error_msg)
            account.status = M3UAccount.Status.ERROR
            account.last_message = error_msg
            account.save(update_fields=['status', 'last_message'])
            send_m3u_update(account.id, "downloading", 100, status="error", error=error_msg)
            return [], False

    # Neither server_url nor uploaded_file is available
    error_msg = "No M3U source available (missing URL and file)"
    logger.error(error_msg)
    account.status = M3UAccount.Status.ERROR
    account.last_message = error_msg
    account.save(update_fields=['status', 'last_message'])
    send_m3u_update(account.id, "downloading", 100, status="error", error=error_msg)
    return [], False

def get_case_insensitive_attr(attributes, key, default=""):
    """Get attribute value using case-insensitive key lookup."""
    for attr_key, attr_value in attributes.items():
        if attr_key.lower() == key.lower():
            return attr_value
    return default

def parse_extinf_line(line: str) -> dict:
    """
    Parse an EXTINF line from an M3U file.
    This function removes the "#EXTINF:" prefix, then splits the remaining
    string on the first comma that is not enclosed in quotes.

    Returns a dictionary with:
      - 'attributes': a dict of attribute key/value pairs (e.g. tvg-id, tvg-logo, group-title)
      - 'display_name': the text after the comma (the fallback display name)
      - 'name': the value from tvg-name (if present) or the display name otherwise.
    """
    if not line.startswith("#EXTINF:"):
        return None
    content = line[len("#EXTINF:"):].strip()
    # Split on the first comma that is not inside quotes.
    parts = re.split(r',(?=(?:[^"]*"[^"]*")*[^"]*$)', content, maxsplit=1)
    if len(parts) != 2:
        return None
    attributes_part, display_name = parts[0], parts[1].strip()
    attrs = dict(re.findall(r'([^\s]+)=["\']([^"\']+)["\']', attributes_part))
    # Use tvg-name attribute if available; otherwise, use the display name.
    name = get_case_insensitive_attr(attrs, 'tvg-name', display_name)
    return {
        'attributes': attrs,
        'display_name': display_name,
        'name': name
    }

def _matches_filters(stream_name: str, group_name: str, filters):
    """Check if a stream or group name matches a precompiled regex filter."""
    compiled_filters = [(re.compile(f.regex_pattern, re.IGNORECASE), f.exclude) for f in filters]
    for pattern, exclude in compiled_filters:
        target = group_name if f.filter_type == 'group' else stream_name
        if pattern.search(target or ''):
            return exclude
    return False

@shared_task
def refresh_m3u_accounts():
    """Queue background parse for all active M3UAccounts."""
    active_accounts = M3UAccount.objects.filter(is_active=True)
    count = 0
    for account in active_accounts:
        refresh_single_m3u_account.delay(account.id)
        count += 1

    msg = f"Queued M3U refresh for {count} active account(s)."
    logger.info(msg)
    return msg

def check_field_lengths(streams_to_create):
    for stream in streams_to_create:
        for field, value in stream.__dict__.items():
            if isinstance(value, str) and len(value) > 255:
                print(f"{field} --- {value}")

        print("")
        print("")

@shared_task
def process_groups(account, groups):
    existing_groups = {group.name: group for group in ChannelGroup.objects.filter(name__in=groups.keys())}
    logger.info(f"Currently {len(existing_groups)} existing groups")

    group_objs = []
    groups_to_create = []
    for group_name, custom_props in groups.items():
        logger.debug(f"Handling group for M3U account {account.id}: {group_name}")
        if (group_name not in existing_groups):
            groups_to_create.append(ChannelGroup(
                name=group_name,
            ))
        else:
            group_objs.append(existing_groups[group_name])

    if groups_to_create:
        logger.debug(f"Creating {len(groups_to_create)} groups")
        created = ChannelGroup.bulk_create_and_fetch(groups_to_create)
        logger.debug(f"Created {len(created)} groups")
        group_objs.extend(created)

    relations = []
    for group in group_objs:
        # Ensure we include the xc_id in the custom_properties
        custom_props = groups.get(group.name, {})
        relations.append(ChannelGroupM3UAccount(
            channel_group=group,
            m3u_account=account,
            custom_properties=json.dumps(custom_props),
            enabled=True,  # Default to enabled
        ))

    ChannelGroupM3UAccount.objects.bulk_create(
        relations,
        ignore_conflicts=True
    )

@shared_task
def process_xc_category(account_id, batch, groups, hash_keys):
    account = M3UAccount.objects.get(id=account_id)

    streams_to_create = []
    streams_to_update = []
    stream_hashes = {}

    try:
        with XCClient(account.server_url, account.username, account.password, account.get_user_agent()) as xc_client:
            # Log the batch details to help with debugging
            logger.debug(f"Processing XC batch: {batch}")

            for group_name, props in batch.items():
                # Check if we have a valid xc_id for this group
                if 'xc_id' not in props:
                    logger.error(f"Missing xc_id for group {group_name} in batch {batch}")
                    continue

                # Get actual group ID from the mapping
                group_id = groups.get(group_name)
                if not group_id:
                    logger.error(f"Group {group_name} not found in enabled groups")
                    continue

                try:
                    logger.debug(f"Fetching streams for XC category: {group_name} (ID: {props['xc_id']})")
                    streams = xc_client.get_live_category_streams(props['xc_id'])

                    if not streams:
                        logger.warning(f"No streams found for XC category {group_name} (ID: {props['xc_id']})")
                        continue

                    logger.debug(f"Found {len(streams)} streams for category {group_name}")

                    for stream in streams:
                        name = stream["name"]
                        url = xc_client.get_stream_url(stream["stream_id"])
                        tvg_id = stream.get("epg_channel_id", "")
                        tvg_logo = stream.get("stream_icon", "")
                        group_title = group_name

                        stream_hash = Stream.generate_hash_key(name, url, tvg_id, hash_keys)
                        stream_props = {
                            "name": name,
                            "url": url,
                            "logo_url": tvg_logo,
                            "tvg_id": tvg_id,
                            "m3u_account": account,
                            "channel_group_id": int(group_id),
                            "stream_hash": stream_hash,
                            "custom_properties": json.dumps(stream),
                        }

                        if stream_hash not in stream_hashes:
                            stream_hashes[stream_hash] = stream_props
                except Exception as e:
                    logger.error(f"Error processing XC category {group_name} (ID: {props['xc_id']}): {str(e)}")
                    continue

        # Process all found streams
        existing_streams = {s.stream_hash: s for s in Stream.objects.filter(stream_hash__in=stream_hashes.keys())}

        for stream_hash, stream_props in stream_hashes.items():
            if stream_hash in existing_streams:
                obj = existing_streams[stream_hash]
                existing_attr = {field.name: getattr(obj, field.name) for field in Stream._meta.fields if field != 'channel_group_id'}
                changed = any(existing_attr[key] != value for key, value in stream_props.items() if key != 'channel_group_id')

                if changed:
                    for key, value in stream_props.items():
                        setattr(obj, key, value)
                    obj.last_seen = timezone.now()
                    obj.updated_at = timezone.now()  # Update timestamp only for changed streams
                    streams_to_update.append(obj)
                    del existing_streams[stream_hash]
                else:
                    # Always update last_seen, even if nothing else changed
                    obj.last_seen = timezone.now()
                    # Don't update updated_at for unchanged streams
                    streams_to_update.append(obj)
                    existing_streams[stream_hash] = obj
            else:
                stream_props["last_seen"] = timezone.now()
                stream_props["updated_at"] = timezone.now()  # Set initial updated_at for new streams
                streams_to_create.append(Stream(**stream_props))

        try:
            with transaction.atomic():
                if streams_to_create:
                    Stream.objects.bulk_create(streams_to_create, ignore_conflicts=True)
                if streams_to_update:
                    # We need to split the bulk update to correctly handle updated_at
                    # First, get the subset of streams that have content changes
                    changed_streams = [s for s in streams_to_update if hasattr(s, 'updated_at') and s.updated_at]
                    unchanged_streams = [s for s in streams_to_update if not hasattr(s, 'updated_at') or not s.updated_at]

                    # Update changed streams with all fields including updated_at
                    if changed_streams:
                        Stream.objects.bulk_update(
                            changed_streams,
                            {key for key in stream_props.keys() if key not in ["m3u_account", "stream_hash"] and key not in hash_keys} | {"last_seen", "updated_at"}
                        )

                    # Update unchanged streams with only last_seen
                    if unchanged_streams:
                        Stream.objects.bulk_update(unchanged_streams, ["last_seen"])

                if len(existing_streams.keys()) > 0:
                    Stream.objects.bulk_update(existing_streams.values(), ["last_seen"])
        except Exception as e:
            logger.error(f"Bulk create failed for XC streams: {str(e)}")

        retval = f"Batch processed: {len(streams_to_create)} created, {len(streams_to_update)} updated."

    except Exception as e:
        logger.error(f"XC category processing error: {str(e)}")
        retval = f"Error processing XC batch: {str(e)}"

    # Aggressive garbage collection
    del streams_to_create, streams_to_update, stream_hashes, existing_streams
    gc.collect()

    return retval

@shared_task
def process_m3u_batch(account_id, batch, groups, hash_keys):
    """Processes a batch of M3U streams using bulk operations."""
    account = M3UAccount.objects.get(id=account_id)

    streams_to_create = []
    streams_to_update = []
    stream_hashes = {}

    # compiled_filters = [(f.filter_type, re.compile(f.regex_pattern, re.IGNORECASE)) for f in filters]
    logger.debug(f"Processing batch of {len(batch)} for M3U account {account_id}")
    for stream_info in batch:
        try:
            name, url = stream_info["name"], stream_info["url"]
            tvg_id, tvg_logo = get_case_insensitive_attr(stream_info["attributes"], "tvg-id", ""), get_case_insensitive_attr(stream_info["attributes"], "tvg-logo", "")
            group_title = get_case_insensitive_attr(stream_info["attributes"], "group-title", "Default Group")

            # Filter out disabled groups for this account
            if group_title not in groups:
                logger.debug(f"Skipping stream in disabled group: {group_title}")
                continue

            stream_hash = Stream.generate_hash_key(name, url, tvg_id, hash_keys)
            stream_props = {
                "name": name,
                "url": url,
                "logo_url": tvg_logo,
                "tvg_id": tvg_id,
                "m3u_account": account,
                "channel_group_id": int(groups.get(group_title)),
                "stream_hash": stream_hash,
                "custom_properties": json.dumps(stream_info["attributes"]),
            }

            if stream_hash not in stream_hashes:
                stream_hashes[stream_hash] = stream_props
        except Exception as e:
            logger.error(f"Failed to process stream {name}: {e}")
            logger.error(json.dumps(stream_info))

    existing_streams = {s.stream_hash: s for s in Stream.objects.filter(stream_hash__in=stream_hashes.keys())}

    for stream_hash, stream_props in stream_hashes.items():
        if stream_hash in existing_streams:
            obj = existing_streams[stream_hash]
            existing_attr = {field.name: getattr(obj, field.name) for field in Stream._meta.fields if field != 'channel_group_id'}
            changed = any(existing_attr[key] != value for key, value in stream_props.items() if key != 'channel_group_id')

            if changed:
                for key, value in stream_props.items():
                    setattr(obj, key, value)
                obj.last_seen = timezone.now()
                obj.updated_at = timezone.now()  # Update timestamp only for changed streams
                streams_to_update.append(obj)
                del existing_streams[stream_hash]
            else:
                # Always update last_seen, even if nothing else changed
                obj.last_seen = timezone.now()
                # Don't update updated_at for unchanged streams
                streams_to_update.append(obj)
                existing_streams[stream_hash] = obj
        else:
            stream_props["last_seen"] = timezone.now()
            stream_props["updated_at"] = timezone.now()  # Set initial updated_at for new streams
            streams_to_create.append(Stream(**stream_props))

    try:
        with transaction.atomic():
            if streams_to_create:
                Stream.objects.bulk_create(streams_to_create, ignore_conflicts=True)
            if streams_to_update:
                # We need to split the bulk update to correctly handle updated_at
                # First, get the subset of streams that have content changes
                changed_streams = [s for s in streams_to_update if hasattr(s, 'updated_at') and s.updated_at]
                unchanged_streams = [s for s in streams_to_update if not hasattr(s, 'updated_at') or not s.updated_at]

                # Update changed streams with all fields including updated_at
                if changed_streams:
                    Stream.objects.bulk_update(
                        changed_streams,
                        {key for key in stream_props.keys() if key not in ["m3u_account", "stream_hash"] and key not in hash_keys} | {"last_seen", "updated_at"}
                    )

                # Update unchanged streams with only last_seen
                if unchanged_streams:
                    Stream.objects.bulk_update(unchanged_streams, ["last_seen"])

            if len(existing_streams.keys()) > 0:
                Stream.objects.bulk_update(existing_streams.values(), ["last_seen"])
    except Exception as e:
        logger.error(f"Bulk create failed: {str(e)}")

    retval = f"M3U account: {account_id}, Batch processed: {len(streams_to_create)} created, {len(streams_to_update)} updated."

    # Aggressive garbage collection
    #del streams_to_create, streams_to_update, stream_hashes, existing_streams
    #from core.utils import cleanup_memory
    #cleanup_memory(log_usage=True, force_collection=True)

    return retval

def cleanup_streams(account_id, scan_start_time=timezone.now):
    account = M3UAccount.objects.get(id=account_id, is_active=True)
    existing_groups = ChannelGroup.objects.filter(
        m3u_account__m3u_account=account,
        m3u_account__enabled=True,
    ).values_list('id', flat=True)
    logger.info(f"Found {len(existing_groups)} active groups for M3U account {account_id}")

    # Calculate cutoff date for stale streams
    stale_cutoff = scan_start_time - timezone.timedelta(days=account.stale_stream_days)
    logger.info(f"Removing streams not seen since {stale_cutoff} for M3U account {account_id}")

    # Delete streams that are not in active groups
    streams_to_delete = Stream.objects.filter(
        m3u_account=account
    ).exclude(
        channel_group__in=existing_groups
    )

    # Also delete streams that haven't been seen for longer than stale_stream_days
    stale_streams = Stream.objects.filter(
        m3u_account=account,
        last_seen__lt=stale_cutoff
    )

    deleted_count = streams_to_delete.count()
    stale_count = stale_streams.count()

    streams_to_delete.delete()
    stale_streams.delete()

    total_deleted = deleted_count + stale_count
    logger.info(f"Cleanup for M3U account {account_id} complete: {deleted_count} streams removed due to group filter, {stale_count} removed as stale")

    # Return the total count of deleted streams
    return total_deleted

@shared_task
def refresh_m3u_groups(account_id, use_cache=False, full_refresh=False):
    if not acquire_task_lock('refresh_m3u_account_groups', account_id):
        return f"Task already running for account_id={account_id}.", None

    try:
        account = M3UAccount.objects.get(id=account_id, is_active=True)
    except M3UAccount.DoesNotExist:
        release_task_lock('refresh_m3u_account_groups', account_id)
        return f"M3UAccount with ID={account_id} not found or inactive.", None

    extinf_data = []
    groups = {"Default Group": {}}

    if account.account_type == M3UAccount.Types.XC:
        # Log detailed information about the account
        logger.info(f"Processing XC account {account_id} with URL: {account.server_url}")
        logger.debug(f"Username: {account.username}, Has password: {'Yes' if account.password else 'No'}")

        # Validate required fields
        if not account.server_url:
            error_msg = "Missing server URL for Xtream Codes account"
            logger.error(error_msg)
            account.status = M3UAccount.Status.ERROR
            account.last_message = error_msg
            account.save(update_fields=['status', 'last_message'])
            send_m3u_update(account_id, "processing_groups", 100, status="error", error=error_msg)
            release_task_lock('refresh_m3u_account_groups', account_id)
            return error_msg, None

        if not account.username or not account.password:
            error_msg = "Missing username or password for Xtream Codes account"
            logger.error(error_msg)
            account.status = M3UAccount.Status.ERROR
            account.last_message = error_msg
            account.save(update_fields=['status', 'last_message'])
            send_m3u_update(account_id, "processing_groups", 100, status="error", error=error_msg)
            release_task_lock('refresh_m3u_account_groups', account_id)
            return error_msg, None

        try:
            # Ensure server URL is properly formatted
            server_url = account.server_url.rstrip('/')
            if not (server_url.startswith('http://') or server_url.startswith('https://')):
                server_url = f"http://{server_url}"

            # User agent handling - completely rewritten
            try:
                # Debug the user agent issue
                logger.debug(f"Getting user agent for account {account.id}")

                # Use a hardcoded user agent string to avoid any issues with object structure
                user_agent_string = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

                try:
                    # Try to get the user agent directly from the database
                    if account.user_agent_id:
                        ua_obj = UserAgent.objects.get(id=account.user_agent_id)
                        if ua_obj and hasattr(ua_obj, 'user_agent') and ua_obj.user_agent:
                            user_agent_string = ua_obj.user_agent
                            logger.debug(f"Using user agent from account: {user_agent_string}")
                    else:
                        # Get default user agent from CoreSettings
                        default_ua_id = CoreSettings.get_default_user_agent_id()
                        logger.debug(f"Default user agent ID from settings: {default_ua_id}")
                        if default_ua_id:
                            ua_obj = UserAgent.objects.get(id=default_ua_id)
                            if ua_obj and hasattr(ua_obj, 'user_agent') and ua_obj.user_agent:
                                user_agent_string = ua_obj.user_agent
                                logger.debug(f"Using default user agent: {user_agent_string}")
                except Exception as e:
                    logger.warning(f"Error getting user agent, using fallback: {str(e)}")

                logger.debug(f"Final user agent string: {user_agent_string}")
            except Exception as e:
                user_agent_string = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                logger.warning(f"Exception in user agent handling, using fallback: {str(e)}")

            logger.info(f"Creating XCClient with URL: {server_url}, Username: {account.username}, User-Agent: {user_agent_string}")

            # Create XCClient with explicit error handling
            try:
                with XCClient(server_url, account.username, account.password, user_agent_string) as xc_client:
                    logger.info(f"XCClient instance created successfully")

                    # Authenticate with detailed error handling
                    try:
                        logger.debug(f"Authenticating with XC server {server_url}")
                        auth_result = xc_client.authenticate()
                        logger.debug(f"Authentication response: {auth_result}")
                    except Exception as e:
                        error_msg = f"Failed to authenticate with XC server: {str(e)}"
                        logger.error(error_msg)
                        account.status = M3UAccount.Status.ERROR
                        account.last_message = error_msg
                        account.save(update_fields=['status', 'last_message'])
                        send_m3u_update(account_id, "processing_groups", 100, status="error", error=error_msg)
                        release_task_lock('refresh_m3u_account_groups', account_id)
                        return error_msg, None

                    # Get categories with detailed error handling
                    try:
                        logger.info(f"Getting live categories from XC server")
                        xc_categories = xc_client.get_live_categories()
                        logger.info(f"Found {len(xc_categories)} categories: {xc_categories}")

                        # Validate response
                        if not isinstance(xc_categories, list):
                            error_msg = f"Unexpected response from XC server: {xc_categories}"
                            logger.error(error_msg)
                            account.status = M3UAccount.Status.ERROR
                            account.last_message = error_msg
                            account.save(update_fields=['status', 'last_message'])
                            send_m3u_update(account_id, "processing_groups", 100, status="error", error=error_msg)
                            release_task_lock('refresh_m3u_account_groups', account_id)
                            return error_msg, None

                        if len(xc_categories) == 0:
                            logger.warning("No categories found in XC server response")

                        for category in xc_categories:
                            cat_name = category.get("category_name", "Unknown Category")
                            cat_id = category.get("category_id", "0")
                            logger.info(f"Adding category: {cat_name} (ID: {cat_id})")
                            groups[cat_name] = {
                                "xc_id": cat_id,
                            }
                    except Exception as e:
                        error_msg = f"Failed to get categories from XC server: {str(e)}"
                        logger.error(error_msg)
                        account.status = M3UAccount.Status.ERROR
                        account.last_message = error_msg
                        account.save(update_fields=['status', 'last_message'])
                        send_m3u_update(account_id, "processing_groups", 100, status="error", error=error_msg)
                        release_task_lock('refresh_m3u_account_groups', account_id)
                        return error_msg, None

            except Exception as e:
                error_msg = f"Failed to create XC Client: {str(e)}"
                logger.error(error_msg)
                account.status = M3UAccount.Status.ERROR
                account.last_message = error_msg
                account.save(update_fields=['status', 'last_message'])
                send_m3u_update(account_id, "processing_groups", 100, status="error", error=error_msg)
                release_task_lock('refresh_m3u_account_groups', account_id)
                return error_msg, None
        except Exception as e:
            error_msg = f"Unexpected error occurred in XC Client: {str(e)}"
            logger.error(error_msg)
            account.status = M3UAccount.Status.ERROR
            account.last_message = error_msg
            account.save(update_fields=['status', 'last_message'])
            send_m3u_update(account_id, "processing_groups", 100, status="error", error=error_msg)
            release_task_lock('refresh_m3u_account_groups', account_id)
            return error_msg, None
    else:
        # Here's the key change - use the success flag from fetch_m3u_lines
        lines, success = fetch_m3u_lines(account, use_cache)
        if not success:
            # If fetch failed, don't continue processing
            release_task_lock('refresh_m3u_account_groups', account_id)
            return f"Failed to fetch M3U data for account_id={account_id}.", None

        # Log basic file structure for debugging
        logger.debug(f"Processing {len(lines)} lines from M3U file")

        line_count = 0
        extinf_count = 0
        url_count = 0
        valid_stream_count = 0
        problematic_lines = []

        for line_index, line in enumerate(lines):
            line_count += 1
            line = line.strip()

            if line.startswith("#EXTINF"):
                extinf_count += 1
                parsed = parse_extinf_line(line)
                if parsed:
                    group_title_attr = get_case_insensitive_attr(parsed["attributes"], "group-title", "")
                    if group_title_attr:
                        group_name = group_title_attr
                        # Log new groups as they're discovered
                        if group_name not in groups:
                            logger.debug(f"Found new group for M3U account {account_id}: '{group_name}'")
                        groups[group_name] = {}

                    extinf_data.append(parsed)
                else:
                    # Log problematic EXTINF lines
                    logger.warning(f"Failed to parse EXTINF at line {line_index+1}: {line[:200]}")
                    problematic_lines.append((line_index+1, line[:200]))

            elif extinf_data and line.startswith("http"):
                url_count += 1
                # Associate URL with the last EXTINF line
                extinf_data[-1]["url"] = line
                valid_stream_count += 1

                # Periodically log progress for large files
                if valid_stream_count % 1000 == 0:
                    logger.debug(f"Processed {valid_stream_count} valid streams so far for M3U account: {account_id}")

        # Log summary statistics
        logger.info(f"M3U parsing complete - Lines: {line_count}, EXTINF: {extinf_count}, URLs: {url_count}, Valid streams: {valid_stream_count}")

        if problematic_lines:
            logger.warning(f"Found {len(problematic_lines)} problematic lines during parsing")
            for i, (line_num, content) in enumerate(problematic_lines[:10]):  # Log max 10 examples
                logger.warning(f"Problematic line #{i+1} at line {line_num}: {content}")
            if len(problematic_lines) > 10:
                logger.warning(f"... and {len(problematic_lines) - 10} more problematic lines")

        # Log group statistics
        logger.info(f"Found {len(groups)} groups in M3U file: {', '.join(list(groups.keys())[:20])}" +
                   ("..." if len(groups) > 20 else ""))

        # Cache processed data
        cache_path = os.path.join(m3u_dir, f"{account_id}.json")
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump({
                "extinf_data": extinf_data,
                "groups": groups,
            }, f)
            logger.debug(f"Cached parsed M3U data to {cache_path}")

    send_m3u_update(account_id, "processing_groups", 0)

    process_groups(account, groups)

    release_task_lock('refresh_m3u_account_groups', account_id)



    if not full_refresh:
        # Use update() instead of save() to avoid triggering signals
        M3UAccount.objects.filter(id=account_id).update(
            status=M3UAccount.Status.PENDING_SETUP,
            last_message="M3U groups loaded. Please select groups or refresh M3U to complete setup."
        )
        send_m3u_update(account_id, "processing_groups", 100, status="pending_setup", message="M3U groups loaded. Please select groups or refresh M3U to complete setup.")

    return extinf_data, groups

def delete_m3u_refresh_task_by_id(account_id):
    """
    Delete the periodic task associated with an M3U account ID.
    Can be called directly or from the post_delete signal.
    Returns True if a task was found and deleted, False otherwise.
    """
    try:
        task = None
        task_name = f"m3u_account-refresh-{account_id}"

        # Look for task by name
        try:
            from django_celery_beat.models import PeriodicTask, IntervalSchedule
            task = PeriodicTask.objects.get(name=task_name)
            logger.debug(f"Found task by name: {task.id} for M3UAccount {account_id}")
        except PeriodicTask.DoesNotExist:
            logger.warning(f"No PeriodicTask found with name {task_name}")
            return False

        # Now delete the task and its interval
        if task:
            # Store interval info before deleting the task
            interval_id = None
            if hasattr(task, 'interval') and task.interval:
                interval_id = task.interval.id

                # Count how many TOTAL tasks use this interval (including this one)
                tasks_with_same_interval = PeriodicTask.objects.filter(interval_id=interval_id).count()
                logger.debug(f"Interval {interval_id} is used by {tasks_with_same_interval} tasks total")

            # Delete the task first
            task_id = task.id
            task.delete()
            logger.debug(f"Successfully deleted periodic task {task_id}")

            # Now check if we should delete the interval
            # We only delete if it was the ONLY task using this interval
            if interval_id and tasks_with_same_interval == 1:
                try:
                    interval = IntervalSchedule.objects.get(id=interval_id)
                    logger.debug(f"Deleting interval schedule {interval_id} (not shared with other tasks)")
                    interval.delete()
                    logger.debug(f"Successfully deleted interval {interval_id}")
                except IntervalSchedule.DoesNotExist:
                    logger.warning(f"Interval {interval_id} no longer exists")
            elif interval_id:
                logger.debug(f"Not deleting interval {interval_id} as it's shared with {tasks_with_same_interval-1} other tasks")

            return True
        return False
    except Exception as e:
        logger.error(f"Error deleting periodic task for M3UAccount {account_id}: {str(e)}", exc_info=True)
        return False

@shared_task
def sync_auto_channels(account_id, scan_start_time=None):
    """
    Automatically create/update/delete channels to match streams in groups with auto_channel_sync enabled.
    Preserves existing channel UUIDs to maintain M3U link integrity.
    Called after M3U refresh completes successfully.
    """
    from apps.channels.models import Channel, ChannelGroup, ChannelGroupM3UAccount, Stream, ChannelStream
    from apps.epg.models import EPGData
    from django.utils import timezone

    try:
        account = M3UAccount.objects.get(id=account_id)
        logger.info(f"Starting auto channel sync for M3U account {account.name}")

        # Always use scan_start_time as the cutoff for last_seen
        if scan_start_time is not None:
            if isinstance(scan_start_time, str):
                scan_start_time = timezone.datetime.fromisoformat(scan_start_time)
        else:
            scan_start_time = timezone.now()

        # Get groups with auto sync enabled for this account
        auto_sync_groups = ChannelGroupM3UAccount.objects.filter(
            m3u_account=account,
            enabled=True,
            auto_channel_sync=True
        ).select_related('channel_group')

        channels_created = 0
        channels_updated = 0
        channels_deleted = 0

        for group_relation in auto_sync_groups:
            channel_group = group_relation.channel_group
            start_number = group_relation.auto_sync_channel_start or 1.0

            # Get force_dummy_epg, group_override, and regex patterns from group custom_properties
            group_custom_props = {}
            force_dummy_epg = False
            override_group_id = None
            name_regex_pattern = None
            name_replace_pattern = None
            name_match_regex = None
            channel_profile_ids = None
            channel_sort_order = None
            if group_relation.custom_properties:
                try:
                    group_custom_props = json.loads(group_relation.custom_properties)
                    force_dummy_epg = group_custom_props.get("force_dummy_epg", False)
                    override_group_id = group_custom_props.get("group_override")
                    name_regex_pattern = group_custom_props.get("name_regex_pattern")
                    name_replace_pattern = group_custom_props.get("name_replace_pattern")
                    name_match_regex = group_custom_props.get("name_match_regex")
                    channel_profile_ids = group_custom_props.get("channel_profile_ids")
                    channel_sort_order = group_custom_props.get("channel_sort_order")
                except Exception:
                    force_dummy_epg = False
                    override_group_id = None
                    name_regex_pattern = None
                    name_replace_pattern = None
                    name_match_regex = None
                    channel_profile_ids = None
                    channel_sort_order = None

            # Determine which group to use for created channels
            target_group = channel_group
            if override_group_id:
                try:
                    target_group = ChannelGroup.objects.get(id=override_group_id)
                    logger.info(f"Using override group '{target_group.name}' instead of '{channel_group.name}' for auto-created channels")
                except ChannelGroup.DoesNotExist:
                    logger.warning(f"Override group with ID {override_group_id} not found, using original group '{channel_group.name}'")

            logger.info(f"Processing auto sync for group: {channel_group.name} (start: {start_number})")

            # Get all current streams in this group for this M3U account, filter out stale streams
            current_streams = Stream.objects.filter(
                m3u_account=account,
                channel_group=channel_group,
                last_seen__gte=scan_start_time
            )

            # --- FILTER STREAMS BY NAME MATCH REGEX IF SPECIFIED ---
            if name_match_regex:
                try:
                    current_streams = current_streams.filter(
                        name__iregex=name_match_regex
                    )
                except re.error as e:
                    logger.warning(f"Invalid name_match_regex '{name_match_regex}' for group '{channel_group.name}': {e}. Skipping name filter.")

            # --- APPLY CHANNEL SORT ORDER ---
            streams_is_list = False  # Track if we converted to list
            if channel_sort_order and channel_sort_order != '':
                if channel_sort_order == 'name':
                    # Use natural sorting for names to handle numbers correctly
                    current_streams = list(current_streams)
                    current_streams.sort(key=lambda stream: natural_sort_key(stream.name))
                    streams_is_list = True
                elif channel_sort_order == 'tvg_id':
                    current_streams = current_streams.order_by('tvg_id')
                elif channel_sort_order == 'updated_at':
                    current_streams = current_streams.order_by('updated_at')
                else:
                    logger.warning(f"Unknown channel_sort_order '{channel_sort_order}' for group '{channel_group.name}'. Using provider order.")
                    current_streams = current_streams.order_by('id')
            else:
                current_streams = current_streams.order_by('id')
            # If channel_sort_order is empty or None, use provider order (no additional sorting)

            # Get existing auto-created channels for this account (regardless of current group)
            # We'll find them by their stream associations instead of just group location
            existing_channels = Channel.objects.filter(
                auto_created=True,
                auto_created_by=account
            ).select_related('logo', 'epg_data')

            # Create mapping of existing channels by their associated stream
            # This approach finds channels even if they've been moved to different groups
            existing_channel_map = {}
            for channel in existing_channels:
                # Get streams associated with this channel that belong to our M3U account and original group
                channel_streams = ChannelStream.objects.filter(
                    channel=channel,
                    stream__m3u_account=account,
                    stream__channel_group=channel_group  # Match streams from the original group
                ).select_related('stream')

                # Map each of our M3U account's streams to this channel
                for channel_stream in channel_streams:
                    if channel_stream.stream:
                        existing_channel_map[channel_stream.stream.id] = channel

            # Track which streams we've processed
            processed_stream_ids = set()

            # Check if we have streams - handle both QuerySet and list cases
            has_streams = len(current_streams) > 0 if streams_is_list else current_streams.exists()

            if not has_streams:
                logger.debug(f"No streams found in group {channel_group.name}")
                # Delete all existing auto channels if no streams
                channels_to_delete = [ch for ch in existing_channel_map.values()]
                if channels_to_delete:
                    deleted_count = len(channels_to_delete)
                    Channel.objects.filter(id__in=[ch.id for ch in channels_to_delete]).delete()
                    channels_deleted += deleted_count
                    logger.debug(f"Deleted {deleted_count} auto channels (no streams remaining)")
                continue

            # Prepare profiles to assign to new channels
            from apps.channels.models import ChannelProfile, ChannelProfileMembership
            if channel_profile_ids and isinstance(channel_profile_ids, list) and len(channel_profile_ids) > 0:
                # Convert all to int (in case they're strings)
                try:
                    profile_ids = [int(pid) for pid in channel_profile_ids]
                except Exception:
                    profile_ids = []
                profiles_to_assign = list(ChannelProfile.objects.filter(id__in=profile_ids))
            else:
                profiles_to_assign = list(ChannelProfile.objects.all())

            # Process each current stream
            current_channel_number = start_number

            # Always renumber all existing channels to match current sort order
            # This ensures channels are always in the correct sequence
            channels_to_renumber = []
            temp_channel_number = start_number

            # Get all channel numbers that are already in use by other channels (not auto-created by this account)
            used_numbers = set(Channel.objects.exclude(
                auto_created=True,
                auto_created_by=account
            ).values_list('channel_number', flat=True))

            for stream in current_streams:
                if stream.id in existing_channel_map:
                    channel = existing_channel_map[stream.id]

                    # Find next available number starting from temp_channel_number
                    target_number = temp_channel_number
                    while target_number in used_numbers:
                        target_number += 1

                    # Add this number to used_numbers so we don't reuse it in this batch
                    used_numbers.add(target_number)

                    if channel.channel_number != target_number:
                        channel.channel_number = target_number
                        channels_to_renumber.append(channel)
                        logger.debug(f"Will renumber channel '{channel.name}' to {target_number}")

                    temp_channel_number += 1.0
                    if temp_channel_number % 1 != 0:  # Has decimal
                        temp_channel_number = int(temp_channel_number) + 1.0

            # Bulk update channel numbers if any need renumbering
            if channels_to_renumber:
                Channel.objects.bulk_update(channels_to_renumber, ['channel_number'])
                logger.info(f"Renumbered {len(channels_to_renumber)} channels to maintain sort order")

            # Reset channel number counter for processing new channels
            current_channel_number = start_number

            for stream in current_streams:
                processed_stream_ids.add(stream.id)
                try:
                    # Parse custom properties for additional info
                    stream_custom_props = json.loads(stream.custom_properties) if stream.custom_properties else {}
                    tvc_guide_stationid = stream_custom_props.get("tvc-guide-stationid")

                    # --- REGEX FIND/REPLACE LOGIC ---
                    original_name = stream.name
                    new_name = original_name
                    if name_regex_pattern is not None:
                        # If replace is None, treat as empty string (remove match)
                        replace = name_replace_pattern if name_replace_pattern is not None else ''
                        try:
                            new_name = re.sub(name_regex_pattern, replace, original_name)
                        except re.error as e:
                            logger.warning(f"Regex error for group '{channel_group.name}': {e}. Using original name.")
                            new_name = original_name

                    # Check if we already have a channel for this stream
                    existing_channel = existing_channel_map.get(stream.id)

                    if existing_channel:
                        # Update existing channel if needed (channel number already handled above)
                        channel_updated = False

                        # Update M3U source values and handle user-edited values intelligently
                        # Only overwrite user-edited values if M3U source has changed
                        
                        # Handle name updates - only overwrite updated_name if M3U name actually changed
                        if existing_channel.m3u_name != new_name:
                            # M3U name has changed, update it
                            existing_channel.m3u_name = new_name
                            channel_updated = True
                            
                            # Only overwrite updated_name if user hasn't customized it
                            # (i.e., if updated_name is None or matches the old M3U name)
                            if existing_channel.updated_name is None or existing_channel.updated_name == existing_channel.name:
                                existing_channel.updated_name = None  # Reset to use M3U name
                                existing_channel.name = new_name  # Update for backward compatibility
                            # If user has customized the name, keep updated_name and don't update name field
                        elif existing_channel.name != new_name:
                            # Fallback for backward compatibility - update name field if it doesn't match
                            existing_channel.name = new_name
                            if existing_channel.m3u_name is None:
                                existing_channel.m3u_name = new_name
                            channel_updated = True

                        if existing_channel.tvg_id != stream.tvg_id:
                            existing_channel.tvg_id = stream.tvg_id
                            channel_updated = True

                        if existing_channel.tvc_guide_stationid != tvc_guide_stationid:
                            existing_channel.tvc_guide_stationid = tvc_guide_stationid
                            channel_updated = True

                        # Check if channel group needs to be updated (in case override was added/changed)
                        if existing_channel.channel_group != target_group:
                            existing_channel.channel_group = target_group
                            channel_updated = True
                            logger.info(f"Moved auto channel '{existing_channel.name}' from '{existing_channel.channel_group.name if existing_channel.channel_group else 'None'}' to '{target_group.name}'")

                        # Handle logo updates with smart user-edited value preservation
                        if existing_channel.m3u_logo_url != stream.logo_url:
                            # M3U logo URL has changed, update it
                            existing_channel.m3u_logo_url = stream.logo_url
                            channel_updated = True
                            
                            # Only overwrite updated_logo if user hasn't customized it
                            if existing_channel.updated_logo is None:
                                # User hasn't customized logo, update the fallback logo field
                                current_logo = None
                                if stream.logo_url:
                                    from apps.channels.models import Logo
                                    current_logo, _ = Logo.objects.get_or_create(
                                        url=stream.logo_url,
                                        defaults={"name": stream.name or stream.tvg_id or "Unknown"}
                                    )
                                existing_channel.logo = current_logo
                            # If user has customized the logo (updated_logo is set), don't touch it
                        else:
                            # M3U logo URL hasn't changed, but ensure logo field is populated if needed
                            if existing_channel.logo is None and stream.logo_url and existing_channel.updated_logo is None:
                                from apps.channels.models import Logo
                                current_logo, _ = Logo.objects.get_or_create(
                                    url=stream.logo_url,
                                    defaults={"name": stream.name or stream.tvg_id or "Unknown"}
                                )
                                existing_channel.logo = current_logo
                                channel_updated = True

                        # Handle EPG data updates
                        current_epg_data = None
                        if stream.tvg_id and not force_dummy_epg:
                            current_epg_data = EPGData.objects.filter(tvg_id=stream.tvg_id).first()

                        if existing_channel.epg_data != current_epg_data:
                            existing_channel.epg_data = current_epg_data
                            channel_updated = True

                        if channel_updated:
                            existing_channel.save()
                            channels_updated += 1
                            logger.debug(f"Updated auto channel: {existing_channel.channel_number} - {existing_channel.name}")

                        # Update channel profile memberships for existing channels
                        current_memberships = set(
                            ChannelProfileMembership.objects.filter(
                                channel=existing_channel,
                                enabled=True
                            ).values_list('channel_profile_id', flat=True)
                        )

                        target_profile_ids = set(profile.id for profile in profiles_to_assign)

                        # Only update if memberships have changed
                        if current_memberships != target_profile_ids:
                            # Disable all current memberships
                            ChannelProfileMembership.objects.filter(
                                channel=existing_channel
                            ).update(enabled=False)

                            # Enable/create memberships for target profiles
                            for profile in profiles_to_assign:
                                membership, created = ChannelProfileMembership.objects.get_or_create(
                                    channel_profile=profile,
                                    channel=existing_channel,
                                    defaults={'enabled': True}
                                )
                                if not created and not membership.enabled:
                                    membership.enabled = True
                                    membership.save()

                            logger.debug(f"Updated profile memberships for auto channel: {existing_channel.name}")

                    else:
                        # Create new channel
                        # Find next available channel number
                        target_number = current_channel_number
                        while target_number in used_numbers:
                            target_number += 1

                        # Add this number to used_numbers
                        used_numbers.add(target_number)

                        channel = Channel.objects.create(
                            channel_number=target_number,
                            name=new_name,
                            m3u_name=new_name,  # Store M3U source name
                            m3u_logo_url=stream.logo_url,  # Store M3U source logo URL
                            # updated_name and updated_logo remain None for new channels (use M3U values)
                            tvg_id=stream.tvg_id,
                            tvc_guide_stationid=tvc_guide_stationid,
                            channel_group=target_group,
                            user_level=0,
                            auto_created=True,
                            auto_created_by=account
                        )

                        # Associate the stream with the channel
                        ChannelStream.objects.create(
                            channel=channel,
                            stream=stream,
                            order=0
                        )

                        # Assign to correct profiles
                        memberships = [
                            ChannelProfileMembership(channel_profile=profile, channel=channel, enabled=True)
                            for profile in profiles_to_assign
                        ]
                        if memberships:
                            ChannelProfileMembership.objects.bulk_create(memberships)

                        # Try to match EPG data
                        if stream.tvg_id and not force_dummy_epg:
                            epg_data = EPGData.objects.filter(tvg_id=stream.tvg_id).first()
                            if epg_data:
                                channel.epg_data = epg_data
                                channel.save(update_fields=['epg_data'])
                        elif stream.tvg_id and force_dummy_epg:
                            channel.epg_data = None
                            channel.save(update_fields=['epg_data'])

                        # Handle logo
                        if stream.logo_url:
                            from apps.channels.models import Logo
                            logo, _ = Logo.objects.get_or_create(
                                url=stream.logo_url,
                                defaults={"name": stream.name or stream.tvg_id or "Unknown"}
                            )
                            channel.logo = logo
                            channel.save(update_fields=['logo'])

                        channels_created += 1
                        logger.debug(f"Created auto channel: {channel.channel_number} - {channel.name}")

                    # Increment channel number for next iteration
                    current_channel_number += 1.0
                    if current_channel_number % 1 != 0:  # Has decimal
                        current_channel_number = int(current_channel_number) + 1.0

                except Exception as e:
                    logger.error(f"Error processing auto channel for stream {stream.name}: {str(e)}")
                    continue

            # Delete channels for streams that no longer exist
            channels_to_delete = []
            for stream_id, channel in existing_channel_map.items():
                if stream_id not in processed_stream_ids:
                    channels_to_delete.append(channel)

            if channels_to_delete:
                deleted_count = len(channels_to_delete)
                Channel.objects.filter(id__in=[ch.id for ch in channels_to_delete]).delete()
                channels_deleted += deleted_count
                logger.debug(f"Deleted {deleted_count} auto channels for removed streams")

        logger.info(f"Auto channel sync complete for account {account.name}: {channels_created} created, {channels_updated} updated, {channels_deleted} deleted")
        return f"Auto sync: {channels_created} channels created, {channels_updated} updated, {channels_deleted} deleted"

    except Exception as e:
        logger.error(f"Error in auto channel sync for account {account_id}: {str(e)}")
        return f"Auto sync error: {str(e)}"

@shared_task
def refresh_single_m3u_account(account_id):
    """Splits M3U processing into chunks and dispatches them as parallel tasks."""
    if not acquire_task_lock('refresh_single_m3u_account', account_id):
        return f"Task already running for account_id={account_id}."

    # Record start time
    refresh_start_timestamp = timezone.now()  # For the cleanup function
    start_time = time.time()  # For tracking elapsed time as float
    streams_created = 0
    streams_updated = 0
    streams_deleted = 0

    try:
        account = M3UAccount.objects.get(id=account_id, is_active=True)
        if not account.is_active:
            logger.debug(f"Account {account_id} is not active, skipping.")
            release_task_lock('refresh_single_m3u_account', account_id)
            return

        # Set status to fetching
        account.status = M3UAccount.Status.FETCHING
        account.save(update_fields=['status'])

        filters = list(account.filters.all())
    except M3UAccount.DoesNotExist:
        # The M3U account doesn't exist, so delete the periodic task if it exists
        logger.warning(f"M3U account with ID {account_id} not found, but task was triggered. Cleaning up orphaned task.")

        # Call the helper function to delete the task
        if delete_m3u_refresh_task_by_id(account_id):
            logger.info(f"Successfully cleaned up orphaned task for M3U account {account_id}")
        else:
            logger.debug(f"No orphaned task found for M3U account {account_id}")

        release_task_lock('refresh_single_m3u_account', account_id)
        return f"M3UAccount with ID={account_id} not found or inactive, task cleaned up"

    # Fetch M3U lines and handle potential issues
    extinf_data = []
    groups = None

    cache_path = os.path.join(m3u_dir, f"{account_id}.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r') as file:
                data = json.load(file)

            extinf_data = data['extinf_data']
            groups = data['groups']
        except json.JSONDecodeError as e:
            # Handle corrupted JSON file
            logger.error(f"Error parsing cached M3U data for account {account_id}: {str(e)}")

            # Backup the corrupted file for potential analysis
            backup_path = f"{cache_path}.corrupted"
            try:
                os.rename(cache_path, backup_path)
                logger.info(f"Renamed corrupted cache file to {backup_path}")
            except OSError as rename_err:
                logger.warning(f"Failed to rename corrupted cache file: {str(rename_err)}")

            # Reset the data to empty structures
            extinf_data = []
            groups = None
        except Exception as e:
            logger.error(f"Unexpected error reading cached M3U data: {str(e)}")
            extinf_data = []
            groups = None

    if not extinf_data:
        try:
            logger.info(f"Calling refresh_m3u_groups for account {account_id}")
            result = refresh_m3u_groups(account_id, full_refresh=True)
            logger.trace(f"refresh_m3u_groups result: {result}")

            # Check for completely empty result or missing groups
            if not result or result[1] is None:
                logger.error(f"Failed to refresh M3U groups for account {account_id}: {result}")
                release_task_lock('refresh_single_m3u_account', account_id)
                return "Failed to update m3u account - download failed or other error"

            extinf_data, groups = result

            # XC accounts can have empty extinf_data but valid groups
            try:
                account = M3UAccount.objects.get(id=account_id)
                is_xc_account = account.account_type == M3UAccount.Types.XC
            except M3UAccount.DoesNotExist:
                is_xc_account = False

            # For XC accounts, empty extinf_data is normal at this stage
            if not extinf_data and not is_xc_account:
                logger.error(f"No streams found for non-XC account {account_id}")
                account.status = M3UAccount.Status.ERROR
                account.last_message = "No streams found in M3U source"
                account.save(update_fields=['status', 'last_message'])
                send_m3u_update(account_id, "parsing", 100, status="error", error="No streams found")
        except Exception as e:
            logger.error(f"Exception in refresh_m3u_groups: {str(e)}", exc_info=True)
            account.status = M3UAccount.Status.ERROR
            account.last_message = f"Error refreshing M3U groups: {str(e)}"
            account.save(update_fields=['status', 'last_message'])
            send_m3u_update(account_id, "parsing", 100, status="error", error=f"Error refreshing M3U groups: {str(e)}")
            release_task_lock('refresh_single_m3u_account', account_id)
            return "Failed to update m3u account"

    # Only proceed with parsing if we actually have data and no errors were encountered
    # Get account type to handle XC accounts differently
    try:
        is_xc_account = account.account_type == M3UAccount.Types.XC
    except Exception:
        is_xc_account = False

    # Modified validation logic for different account types
    if (not groups) or (not is_xc_account and not extinf_data):
        logger.error(f"No data to process for account {account_id}")
        account.status = M3UAccount.Status.ERROR
        account.last_message = "No data available for processing"
        account.save(update_fields=['status', 'last_message'])
        send_m3u_update(account_id, "parsing", 100, status="error", error="No data available for processing")
        release_task_lock('refresh_single_m3u_account', account_id)
        return "Failed to update m3u account, no data available"

    hash_keys = CoreSettings.get_m3u_hash_key().split(",")

    existing_groups = {group.name: group.id for group in ChannelGroup.objects.filter(
        m3u_account__m3u_account=account,  # Filter by the M3UAccount
        m3u_account__enabled=True  # Filter by the enabled flag in the join table
    )}

    try:
        # Set status to parsing
        account.status = M3UAccount.Status.PARSING
        account.save(update_fields=['status'])

        if account.account_type == M3UAccount.Types.STADNARD:
            logger.debug(f"Processing Standard account ({account_id}) with groups: {existing_groups}")
            # Break into batches and process in parallel
            batches = [extinf_data[i:i + BATCH_SIZE] for i in range(0, len(extinf_data), BATCH_SIZE)]
            task_group = group(process_m3u_batch.s(account_id, batch, existing_groups, hash_keys) for batch in batches)
        else:
            # For XC accounts, get the groups with their custom properties containing xc_id
            logger.debug(f"Processing XC account with groups: {existing_groups}")

            # Get the ChannelGroupM3UAccount entries with their custom_properties
            channel_group_relationships = ChannelGroupM3UAccount.objects.filter(
                m3u_account=account,
                enabled=True
            ).select_related('channel_group')

            filtered_groups = {}
            for rel in channel_group_relationships:
                group_name = rel.channel_group.name
                group_id = rel.channel_group.id

                # Load the custom properties with the xc_id
                try:
                    custom_props = json.loads(rel.custom_properties) if rel.custom_properties else {}
                    if 'xc_id' in custom_props:
                        filtered_groups[group_name] = {
                            'xc_id': custom_props['xc_id'],
                            'channel_group_id': group_id
                        }
                        logger.debug(f"Added group {group_name} with xc_id {custom_props['xc_id']}")
                    else:
                        logger.warning(f"No xc_id found in custom properties for group {group_name}")
                except (json.JSONDecodeError, KeyError) as e:
                    logger.error(f"Error parsing custom properties for group {group_name}: {str(e)}")

            logger.info(f"Filtered {len(filtered_groups)} groups for processing: {filtered_groups}")

            # Batch the groups
            filtered_groups_list = list(filtered_groups.items())
            batches = [
                dict(filtered_groups_list[i:i + 2])
                for i in range(0, len(filtered_groups_list), 2)
            ]

            logger.info(f"Created {len(batches)} batches for XC processing")
            task_group = group(process_xc_category.s(account_id, batch, existing_groups, hash_keys) for batch in batches)

        total_batches = len(batches)
        completed_batches = 0
        streams_processed = 0  # Track total streams processed
        logger.debug(f"Dispatched {len(batches)} parallel tasks for account_id={account_id}.")

        # result = task_group.apply_async()
        result = task_group.apply_async()

        # Wait for all tasks to complete and collect their result IDs
        completed_task_ids = set()
        while completed_batches < total_batches:
            for async_result in result:
                if async_result.ready() and async_result.id not in completed_task_ids:  # If the task has completed and we haven't counted it
                    task_result = async_result.result  # The result of the task
                    logger.debug(f"Task completed with result: {task_result}")

                    # Extract stream counts from result string if available
                    if isinstance(task_result, str):
                        try:
                            created_match = re.search(r"(\d+) created", task_result)
                            updated_match = re.search(r"(\d+) updated", task_result)

                            if created_match and updated_match:
                                created_count = int(created_match.group(1))
                                updated_count = int(updated_match.group(1))
                                streams_processed += created_count + updated_count
                                streams_created += created_count
                                streams_updated += updated_count
                        except (AttributeError, ValueError):
                            pass

                    completed_batches += 1
                    completed_task_ids.add(async_result.id)  # Mark this task as processed

                    # Calculate progress
                    progress = int((completed_batches / total_batches) * 100)

                    # Calculate elapsed time and estimated remaining time
                    current_elapsed = time.time() - start_time
                    if progress > 0:
                        estimated_total = (current_elapsed / progress) * 100
                        time_remaining = max(0, estimated_total - current_elapsed)
                    else:
                        time_remaining = 0

                    # Send progress update via Channels
                    # Don't send 100% because we want to clean up after
                    if progress == 100:
                        progress = 99

                    send_m3u_update(
                        account_id,
                        "parsing",
                        progress,
                        elapsed_time=current_elapsed,
                        time_remaining=time_remaining,
                        streams_processed=streams_processed
                    )

                    # Optionally remove completed task from the group to prevent processing it again
                    result.remove(async_result)
                else:
                    logger.trace(f"Task is still running.")

        # Ensure all database transactions are committed before cleanup
        logger.info(f"All {total_batches} tasks completed, ensuring DB transactions are committed before cleanup")
        # Force a simple DB query to ensure connection sync
        Stream.objects.filter(id=-1).exists()  # This will never find anything but ensures DB sync

        # Now run cleanup
        streams_deleted = cleanup_streams(account_id, refresh_start_timestamp)

        # Run auto channel sync after successful refresh
        auto_sync_message = ""
        try:
            sync_result = sync_auto_channels(account_id, scan_start_time=str(refresh_start_timestamp))
            logger.info(f"Auto channel sync result for account {account_id}: {sync_result}")
            if sync_result and "created" in sync_result:
                auto_sync_message = f" {sync_result}."
        except Exception as e:
            logger.error(f"Error running auto channel sync for account {account_id}: {str(e)}")

        # Calculate elapsed time
        elapsed_time = time.time() - start_time

        # Set status to success and update timestamp BEFORE sending the final update
        account.status = M3UAccount.Status.SUCCESS
        account.last_message = (
            f"Processing completed in {elapsed_time:.1f} seconds. "
            f"Streams: {streams_created} created, {streams_updated} updated, {streams_deleted} removed. "
            f"Total processed: {streams_processed}.{auto_sync_message}"
        )
        account.updated_at = timezone.now()
        account.save(update_fields=['status', 'last_message', 'updated_at'])

        # Send final update with complete metrics and explicitly include success status
        send_m3u_update(
            account_id,
            "parsing",
            100,
            status="success",  # Explicitly set status to success
            elapsed_time=elapsed_time,
            time_remaining=0,
            streams_processed=streams_processed,
            streams_created=streams_created,
            streams_updated=streams_updated,
            streams_deleted=streams_deleted,
            message=account.last_message
        )

    except Exception as e:
        logger.error(f"Error processing M3U for account {account_id}: {str(e)}")
        account.status = M3UAccount.Status.ERROR
        account.last_message = f"Error processing M3U: {str(e)}"
        account.save(update_fields=['status', 'last_message'])
        raise  # Re-raise the exception for Celery to handle

    release_task_lock('refresh_single_m3u_account', account_id)

    # Aggressive garbage collection
    del existing_groups, extinf_data, groups, batches
    from core.utils import cleanup_memory
    cleanup_memory(log_usage=True, force_collection=True)

    # Clean up cache file since we've fully processed it
    if os.path.exists(cache_path):
        os.remove(cache_path)

    return f"Dispatched jobs complete."

def send_m3u_update(account_id, action, progress, **kwargs):
    # Start with the base data dictionary
    data = {
        "progress": progress,
        "type": "m3u_refresh",
        "account": account_id,
        "action": action,
    }

    # Add the status and message if not already in kwargs
    try:
        account = M3UAccount.objects.get(id=account_id)
        if account:
            if "status" not in kwargs:
                data["status"] = account.status
            if "message" not in kwargs and account.last_message:
                data["message"] = account.last_message
    except:
        pass  # If account can't be retrieved, continue without these fields

    # Add the additional key-value pairs from kwargs
    data.update(kwargs)
    send_websocket_update('updates', 'update', data, collect_garbage=False)

    # Explicitly clear data reference to help garbage collection
    data = None
