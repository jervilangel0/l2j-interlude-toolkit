#!/bin/bash
# L2J Mobius C6 Interlude - Server Management Tool
# Easy CLI to manage your server without hunting through config files

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GAME_CONFIG="$SCRIPT_DIR/dist/game/config/main"
CUSTOM_CONFIG="$SCRIPT_DIR/dist/game/config/custom"
LOGIN_CONFIG="$SCRIPT_DIR/dist/login/config/main"
DB_NAME="l2jmobiusc6"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

show_help() {
    echo ""
    echo -e "${CYAN}=== L2J Server Management Tool ===${NC}"
    echo ""
    echo -e "${GREEN}Server Control:${NC}"
    echo "  status          - Check if servers are running"
    echo "  start           - Start login + game server"
    echo "  stop            - Stop all servers"
    echo "  restart         - Restart all servers"
    echo "  rebuild         - Recompile Java source and copy JARs"
    echo ""
    echo -e "${GREEN}Rates:${NC}"
    echo "  rates           - Show current rates"
    echo "  set-rates <N>   - Set XP/SP/Drop/Adena/Spoil all to Nx"
    echo "  set-rate <key> <value> - Set a specific rate"
    echo ""
    echo -e "${GREEN}Account Management:${NC}"
    echo "  gm <username>   - Promote account to GM (access level 200)"
    echo "  accounts        - List all accounts"
    echo "  ban <username>  - Ban an account"
    echo "  unban <username> - Unban an account"
    echo ""
    echo -e "${GREEN}Configuration:${NC}"
    echo "  config          - List all config files"
    echo "  edit <file>     - Open a config file in \$EDITOR"
    echo "  get <file> <key> - Get a config value"
    echo "  set <file> <key> <value> - Set a config value"
    echo ""
    echo -e "${GREEN}Database:${NC}"
    echo "  db              - Open MariaDB shell for game DB"
    echo "  db-reset        - Re-import all SQL files (destructive!)"
    echo "  db-backup       - Backup the database"
    echo ""
    echo -e "${GREEN}Info:${NC}"
    echo "  info            - Show server config summary"
    echo "  players         - Show online characters (from DB)"
    echo "  tree            - Show directory structure"
    echo ""
}

cmd_status() {
    echo -e "${CYAN}=== Server Status ===${NC}"
    GAME_PID=$(pgrep -f "GameServer.jar" 2>/dev/null)
    LOGIN_PID=$(pgrep -f "LoginServer.jar" 2>/dev/null)

    if [ -n "$LOGIN_PID" ]; then
        echo -e "Login Server:  ${GREEN}RUNNING${NC} (PID: $LOGIN_PID)"
    else
        echo -e "Login Server:  ${RED}STOPPED${NC}"
    fi

    if [ -n "$GAME_PID" ]; then
        echo -e "Game Server:   ${GREEN}RUNNING${NC} (PID: $GAME_PID)"
    else
        echo -e "Game Server:   ${RED}STOPPED${NC}"
    fi

    echo ""
    MARIADB_PID=$(pgrep -f "mariadbd" 2>/dev/null)
    if [ -n "$MARIADB_PID" ]; then
        echo -e "MariaDB:       ${GREEN}RUNNING${NC} (PID: $MARIADB_PID)"
    else
        echo -e "MariaDB:       ${RED}STOPPED${NC}"
    fi
}

cmd_start() {
    echo -e "${CYAN}=== Starting L2J Servers ===${NC}"

    # Check MariaDB
    if ! pgrep -f "mariadbd" > /dev/null 2>&1; then
        echo "Starting MariaDB..."
        brew services start mariadb
        sleep 2
    fi

    # Start Login Server
    if pgrep -f "LoginServer.jar" > /dev/null 2>&1; then
        echo -e "${YELLOW}Login Server already running${NC}"
    else
        echo "Starting Login Server..."
        "$SCRIPT_DIR/start-login.sh" &
        sleep 5
    fi

    # Start Game Server
    if pgrep -f "GameServer.jar" > /dev/null 2>&1; then
        echo -e "${YELLOW}Game Server already running${NC}"
    else
        echo "Starting Game Server..."
        "$SCRIPT_DIR/start-game.sh" &
        sleep 3
    fi

    echo ""
    cmd_status
}

cmd_stop() {
    "$SCRIPT_DIR/stop-all.sh"
}

cmd_restart() {
    cmd_stop
    sleep 3
    cmd_start
}

cmd_rates() {
    echo -e "${CYAN}=== Current Rates ===${NC}"
    grep -E "^Rate(Xp|Sp|Drop|Consumable)" "$GAME_CONFIG/Rates.ini" 2>/dev/null
    grep -E "^RateParty" "$GAME_CONFIG/Rates.ini" 2>/dev/null
    grep -E "^RateQuest" "$GAME_CONFIG/Rates.ini" 2>/dev/null
}

cmd_set_rates() {
    local mult=$1
    if [ -z "$mult" ]; then
        echo "Usage: l2j-manage set-rates <multiplier>"
        echo "Example: l2j-manage set-rates 5"
        return 1
    fi

    local file="$GAME_CONFIG/Rates.ini"
    sed -i '' "s/^RateXp = .*/RateXp = ${mult}.00/" "$file"
    sed -i '' "s/^RateSp = .*/RateSp = ${mult}.00/" "$file"
    sed -i '' "s/^RateDropAdena = .*/RateDropAdena = ${mult}.00/" "$file"
    sed -i '' "s/^RateDropItems = .*/RateDropItems = ${mult}.00/" "$file"
    sed -i '' "s/^RateDropSpoil = .*/RateDropSpoil = ${mult}.00/" "$file"
    sed -i '' "s/^RateDropQuest = .*/RateDropQuest = ${mult}.00/" "$file"
    sed -i '' "s/^RateQuestsReward = .*/RateQuestsReward = ${mult}.00/" "$file"

    echo -e "${GREEN}All rates set to ${mult}x${NC}"
    echo ""
    cmd_rates
}

cmd_set_rate() {
    local key=$1
    local value=$2
    if [ -z "$key" ] || [ -z "$value" ]; then
        echo "Usage: l2j-manage set-rate <key> <value>"
        echo "Example: l2j-manage set-rate RateXp 10.00"
        return 1
    fi

    local file="$GAME_CONFIG/Rates.ini"
    sed -i '' "s/^${key} = .*/${key} = ${value}/" "$file"
    echo -e "${GREEN}Set ${key} = ${value}${NC}"
}

cmd_gm() {
    local username=$1
    if [ -z "$username" ]; then
        echo "Usage: l2j-manage gm <username>"
        return 1
    fi

    mariadb -u root "$DB_NAME" -e "UPDATE accounts SET accessLevel = 200 WHERE login = '${username}';" 2>&1
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}Account '${username}' promoted to GM (accessLevel=200)${NC}"
        echo "Note: You need to relog for it to take effect."
    else
        echo -e "${RED}Failed. Make sure the account exists (log in once first with AutoCreateAccounts=True).${NC}"
    fi
}

cmd_accounts() {
    echo -e "${CYAN}=== Accounts ===${NC}"
    mariadb -u root "$DB_NAME" -e "SELECT login, accessLevel, lastactive, lastIP FROM accounts;" 2>/dev/null
    if [ $? -ne 0 ]; then
        echo "No accounts yet, or DB not accessible."
    fi
}

cmd_ban() {
    local username=$1
    if [ -z "$username" ]; then
        echo "Usage: l2j-manage ban <username>"
        return 1
    fi
    mariadb -u root "$DB_NAME" -e "UPDATE accounts SET accessLevel = -100 WHERE login = '${username}';"
    echo -e "${GREEN}Account '${username}' banned${NC}"
}

cmd_unban() {
    local username=$1
    if [ -z "$username" ]; then
        echo "Usage: l2j-manage unban <username>"
        return 1
    fi
    mariadb -u root "$DB_NAME" -e "UPDATE accounts SET accessLevel = 0 WHERE login = '${username}';"
    echo -e "${GREEN}Account '${username}' unbanned${NC}"
}

cmd_config() {
    echo -e "${CYAN}=== Game Server Config Files ===${NC}"
    echo -e "${GREEN}Main:${NC}"
    ls "$GAME_CONFIG/"
    echo ""
    echo -e "${GREEN}Custom:${NC}"
    ls "$CUSTOM_CONFIG/"
    echo ""
    echo -e "${GREEN}Login Server:${NC}"
    ls "$LOGIN_CONFIG/"
    echo ""
    echo -e "${YELLOW}Tip: Use 'l2j-manage edit <filename>' to open in your editor${NC}"
}

cmd_edit() {
    local file=$1
    if [ -z "$file" ]; then
        echo "Usage: l2j-manage edit <filename>"
        echo "Example: l2j-manage edit Rates.ini"
        cmd_config
        return 1
    fi

    # Search for the file in config directories
    local found=""
    for dir in "$GAME_CONFIG" "$CUSTOM_CONFIG" "$LOGIN_CONFIG"; do
        if [ -f "$dir/$file" ]; then
            found="$dir/$file"
            break
        fi
    done

    if [ -z "$found" ]; then
        echo -e "${RED}Config file '$file' not found.${NC}"
        cmd_config
        return 1
    fi

    ${EDITOR:-nano} "$found"
}

cmd_get() {
    local file=$1
    local key=$2
    if [ -z "$file" ] || [ -z "$key" ]; then
        echo "Usage: l2j-manage get <file> <key>"
        return 1
    fi

    local found=""
    for dir in "$GAME_CONFIG" "$CUSTOM_CONFIG" "$LOGIN_CONFIG"; do
        if [ -f "$dir/$file" ]; then
            found="$dir/$file"
            break
        fi
    done

    if [ -z "$found" ]; then
        echo -e "${RED}Config file '$file' not found.${NC}"
        return 1
    fi

    grep "^${key}" "$found"
}

cmd_set() {
    local file=$1
    local key=$2
    local value=$3
    if [ -z "$file" ] || [ -z "$key" ] || [ -z "$value" ]; then
        echo "Usage: l2j-manage set <file> <key> <value>"
        echo "Example: l2j-manage set Server.ini MaximumOnlineUsers 500"
        return 1
    fi

    local found=""
    for dir in "$GAME_CONFIG" "$CUSTOM_CONFIG" "$LOGIN_CONFIG"; do
        if [ -f "$dir/$file" ]; then
            found="$dir/$file"
            break
        fi
    done

    if [ -z "$found" ]; then
        echo -e "${RED}Config file '$file' not found.${NC}"
        return 1
    fi

    sed -i '' "s/^${key} = .*/${key} = ${value}/" "$found"
    echo -e "${GREEN}Set ${key} = ${value} in ${file}${NC}"
}

cmd_db() {
    echo -e "${CYAN}Opening MariaDB shell for ${DB_NAME}...${NC}"
    mariadb -u root "$DB_NAME"
}

cmd_db_reset() {
    echo -e "${RED}WARNING: This will drop and recreate the database!${NC}"
    read -p "Are you sure? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        echo "Cancelled."
        return 0
    fi

    mariadb -u root -e "DROP DATABASE IF EXISTS ${DB_NAME}; CREATE DATABASE ${DB_NAME};"

    for f in "$SCRIPT_DIR/dist/db_installer/sql/login/"*.sql; do
        echo "Importing: $(basename $f)"
        mariadb -u root "$DB_NAME" < "$f"
    done

    for f in "$SCRIPT_DIR/dist/db_installer/sql/game/"*.sql; do
        echo "Importing: $(basename $f)"
        mariadb -u root "$DB_NAME" < "$f"
    done

    echo -e "${GREEN}Database reset complete!${NC}"
}

cmd_db_backup() {
    local backup_dir="$SCRIPT_DIR/dist/backup"
    mkdir -p "$backup_dir"
    local filename="${backup_dir}/${DB_NAME}_$(date +%Y%m%d_%H%M%S).sql"
    mariadb-dump -u root "$DB_NAME" > "$filename"
    echo -e "${GREEN}Backup saved to: ${filename}${NC}"
}

cmd_info() {
    echo -e "${CYAN}=== Server Configuration Summary ===${NC}"
    echo ""
    echo -e "${GREEN}Network:${NC}"
    grep -E "^(ExternalHostname|InternalHostname|GameserverPort|LoginserverPort)" "$GAME_CONFIG/Server.ini" "$LOGIN_CONFIG/LoginServer.ini" 2>/dev/null | sed 's|.*/||'
    echo ""
    echo -e "${GREEN}Database:${NC}"
    grep -E "^(URL |Login |Password )" "$GAME_CONFIG/Server.ini" 2>/dev/null | head -3
    echo ""
    echo -e "${GREEN}Server:${NC}"
    grep -E "^(MaximumOnlineUsers|RequestServerID|AutoCreateAccounts)" "$GAME_CONFIG/Server.ini" "$LOGIN_CONFIG/LoginServer.ini" 2>/dev/null | sed 's|.*/||'
    echo ""
    echo -e "${GREEN}Key Rates:${NC}"
    grep -E "^(RateXp|RateSp|RateDropAdena|RateDropItems|RateDropSpoil)" "$GAME_CONFIG/Rates.ini" 2>/dev/null
}

cmd_players() {
    echo -e "${CYAN}=== Characters in Database ===${NC}"
    mariadb -u root "$DB_NAME" -e "SELECT char_name, level, online, accesslevel FROM characters ORDER BY level DESC LIMIT 20;" 2>/dev/null
    if [ $? -ne 0 ]; then
        echo "No characters yet."
    fi
}

cmd_tree() {
    echo -e "${CYAN}=== Server Directory Structure ===${NC}"
    find "$SCRIPT_DIR" -maxdepth 4 -type d | sed "s|$SCRIPT_DIR|.|" | sort
}

cmd_rebuild() {
    "$SCRIPT_DIR/rebuild.sh"
}

# Main command router
case "${1}" in
    status)     cmd_status ;;
    start)      cmd_start ;;
    stop)       cmd_stop ;;
    restart)    cmd_restart ;;
    rebuild)    cmd_rebuild ;;
    rates)      cmd_rates ;;
    set-rates)  cmd_set_rates "$2" ;;
    set-rate)   cmd_set_rate "$2" "$3" ;;
    gm)         cmd_gm "$2" ;;
    accounts)   cmd_accounts ;;
    ban)        cmd_ban "$2" ;;
    unban)      cmd_unban "$2" ;;
    config)     cmd_config ;;
    edit)       cmd_edit "$2" ;;
    get)        cmd_get "$2" "$3" ;;
    set)        cmd_set "$2" "$3" "$4" ;;
    db)         cmd_db ;;
    db-reset)   cmd_db_reset ;;
    db-backup)  cmd_db_backup ;;
    info)       cmd_info ;;
    players)    cmd_players ;;
    tree)       cmd_tree ;;
    help|--help|-h|"")
        show_help ;;
    *)
        echo -e "${RED}Unknown command: $1${NC}"
        show_help ;;
esac
