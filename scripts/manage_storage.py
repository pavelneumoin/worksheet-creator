"""python scripts/manage_storage.py backup|restore|cleanup --help"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app/backend'))
from utils.backup import create_backup, restore_backup, cleanup_generated


def main():
    parser = argparse.ArgumentParser(description='Резервные копии ЛистОК и очистка старых файлов')
    sub = parser.add_subparsers(dest='command', required=True)
    backup = sub.add_parser('backup'); backup.add_argument('archive')
    restore = sub.add_parser('restore'); restore.add_argument('archive'); restore.add_argument('new_directory')
    cleanup = sub.add_parser('cleanup'); cleanup.add_argument('--apply', action='store_true'); cleanup.add_argument('--days', type=int, default=30)
    provider = sub.add_parser('provider-cleanup'); provider.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'backup': result = create_backup(args.archive)
        elif args.command == 'restore': result = restore_backup(args.archive, args.new_directory)
        elif args.command == 'cleanup': result = cleanup_generated(args.apply, args.days)
        else:
            from utils import provider_files
            if args.apply:
                from dotenv import load_dotenv
                load_dotenv(Path(__file__).resolve().parents[1] / '.env')
                from utils.gigachat_client import _create_client
                with _create_client() as client: result = provider_files.cleanup(client, apply=True)
            else: result = provider_files.cleanup(None)
    except (ValueError, OSError) as exc:
        parser.exit(1, str(exc) + '\n')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()
