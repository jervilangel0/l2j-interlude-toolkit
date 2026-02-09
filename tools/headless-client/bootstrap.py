#!/usr/bin/env python3
"""
Bootstrap — Create N scanner accounts + characters + promote to GM.

Usage:
  python3 bootstrap.py --num 20                # Create 20 accounts + characters
  python3 bootstrap.py --num 20 --promote      # Also promote to GM (accesslevel=1)
  python3 bootstrap.py --num 5 --prefix agent  # Custom prefix: agent01..agent05
  python3 bootstrap.py --promote-only          # Just promote existing characters

Requirements:
  - L2J server running with AutoCreateAccounts=True in login config
  - MariaDB running for --promote (uses `mariadb` CLI)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from l2_client import L2LoginClient, L2GameClient, full_connect_or_create


def create_account_and_character(username: str, password: str,
                                  char_name: str,
                                  login_host: str = "127.0.0.1",
                                  login_port: int = 2106) -> bool:
    """Create an account (via AutoCreateAccounts) and a character.

    Steps:
      1. Login to login server (creates account if AutoCreateAccounts=True)
      2. Connect to game server
      3. If no characters, create one
      4. Disconnect
    """
    print(f"\n{'='*50}")
    print(f"Creating: account={username}, char={char_name}")
    print(f"{'='*50}")

    try:
        game = full_connect_or_create(
            username=username,
            password=password,
            char_name=char_name,
            class_id=0x00,  # Human Fighter
            login_host=login_host,
            login_port=login_port,
        )

        if game:
            print(f"[OK] {char_name} is in world at ({game.x}, {game.y}, {game.z})")
            game.close()
            return True
        else:
            print(f"[FAIL] Could not create {char_name}")
            return False

    except Exception as e:
        print(f"[ERROR] {e}")
        return False


def promote_to_gm(char_names: list[str],
                   db_name: str = "l2jmobiusc6",
                   db_user: str = "root",
                   db_host: str = "127.0.0.1") -> int:
    """Promote characters to GM by setting accesslevel=1 in the database.

    Uses the `mariadb` CLI command (no extra Python deps).
    """
    print(f"\n{'='*50}")
    print(f"Promoting {len(char_names)} characters to GM")
    print(f"{'='*50}")

    promoted = 0
    for name in char_names:
        sql = f"UPDATE characters SET accesslevel = 1 WHERE char_name = '{name}';"
        try:
            result = subprocess.run(
                ["mariadb", "-u", db_user, "-h", db_host, db_name, "-e", sql],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                print(f"  [GM] {name} promoted (accesslevel=1)")
                promoted += 1
            else:
                print(f"  [FAIL] {name}: {result.stderr.strip()}")
        except FileNotFoundError:
            # Try mysql as fallback
            try:
                result = subprocess.run(
                    ["mysql", "-u", db_user, "-h", db_host, db_name, "-e", sql],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    print(f"  [GM] {name} promoted (accesslevel=1)")
                    promoted += 1
                else:
                    print(f"  [FAIL] {name}: {result.stderr.strip()}")
            except FileNotFoundError:
                print("  [ERROR] Neither 'mariadb' nor 'mysql' CLI found!")
                return promoted
        except Exception as e:
            print(f"  [ERROR] {name}: {e}")

    return promoted


def main():
    parser = argparse.ArgumentParser(
        description="Bootstrap scanner accounts + characters + GM promotion",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --num 20                    Create 20 scanner accounts + characters
  %(prog)s --num 20 --promote          Also promote to GM
  %(prog)s --num 5 --prefix agent      Custom prefix: agent01..agent05
  %(prog)s --promote-only --num 20     Just promote existing scanner01..scanner20
        """,
    )

    parser.add_argument("--num", type=int, default=3,
                        help="Number of accounts/characters to create (default: 3)")
    parser.add_argument("--prefix", default="scanner",
                        help="Name prefix (default: scanner → scanner01, scanner02...)")
    parser.add_argument("--password", default="scanner",
                        help="Password for all accounts (default: scanner)")
    parser.add_argument("--promote", action="store_true",
                        help="Promote all characters to GM after creation")
    parser.add_argument("--promote-only", action="store_true",
                        help="Only promote existing characters (skip creation)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Login server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=2106,
                        help="Login server port (default: 2106)")
    parser.add_argument("--db-name", default="l2jmobiusc6",
                        help="Database name (default: l2jmobiusc6)")
    parser.add_argument("--db-user", default="root",
                        help="Database user (default: root)")
    parser.add_argument("--delay", type=float, default=2.0,
                        help="Delay between account creations in seconds (default: 2.0)")

    args = parser.parse_args()

    # Generate names — 3 digits for 100+, 2 digits otherwise
    width = 3 if args.num >= 100 else 2
    names = [f"{args.prefix}{i + 1:0{width}d}" for i in range(args.num)]

    if not args.promote_only:
        # Create accounts + characters
        print(f"\nCreating {args.num} accounts with prefix '{args.prefix}'")
        print(f"Names: {', '.join(names)}")
        print(f"Server: {args.host}:{args.port}")
        print()

        created = 0
        failed = 0
        for i, name in enumerate(names):
            success = create_account_and_character(
                username=name,
                password=args.password,
                char_name=name,
                login_host=args.host,
                login_port=args.port,
            )
            if success:
                created += 1
            else:
                failed += 1

            # Delay between creations to avoid overwhelming the server
            if i < len(names) - 1:
                time.sleep(args.delay)

        print(f"\n{'='*50}")
        print(f"Account creation: {created} OK, {failed} failed")
        print(f"{'='*50}")

    if args.promote or args.promote_only:
        # Wait a moment for DB writes to settle
        time.sleep(1.0)
        promoted = promote_to_gm(names, db_name=args.db_name, db_user=args.db_user)
        print(f"\nGM promotion: {promoted}/{len(names)} promoted")

    print("\nDone!")


if __name__ == "__main__":
    main()
