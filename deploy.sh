#!/bin/bash
# deploy.sh - Deployment script with functions and options

set -e

# Базовые переменные
DOCKER_USERNAME="holyshithappens"
DOCKER_IMAGE_NAME="flbst-bot-mdb"
IMAGE_NAME="$DOCKER_USERNAME/$DOCKER_IMAGE_NAME"
VPS_PATH="flbst-bot-mdb"
GITHUB_REPO="https://github.com/holyshithappens/flibusta_bot_mariadb.git"
BRANCH="master"

# Переменные для хранения введенных данных
VPS_IP=""
VPS_USER=""
DOCKER_PASSWORD=""

# Функции
show_usage() {
    echo "Usage: $0 [OPTION]"
    echo "Deploy script for Flibusta Bot"
    echo ""
    echo "Options:"
    echo "  -u, --update    Quick update (pull and restart containers)"
    echo "  -n, --news      Update only news file"
    echo "  -d, --db-init   Extract SQL files and reinitialize database"
    echo "  -h, --help      Show this help message"
    echo ""
    echo "Without options: Full deployment (build and deploy)"
}

prompt_user_input_vps() {
    echo "🔐 VPS Connection Details"
    read -p "Enter VPS IP address [162.199.167.194]: " input_ip
    read -p "Enter VPS username [holy]: " input_user

    VPS_IP=${input_ip:-"162.199.167.194"}
    VPS_USER=${input_user:-"holy"}
}

prompt_user_input_docker() {
    echo ""
    echo "🔐 Docker Hub authentication needed for user: $DOCKER_USERNAME"
    read -s -p "Enter Docker Hub password or access token: " DOCKER_PASSWORD
    echo
}

setup_directories_and_files() {
    echo ""
    echo "📁 Setting up directories and files on VPS..."

    ssh $VPS_USER@$VPS_IP << EOF
mkdir -p ~/$VPS_PATH/data ~/$VPS_PATH/logs ~/$VPS_PATH/db_init/sql ~/$VPS_PATH/db_backups
EOF

    scp .env.vps $VPS_USER@$VPS_IP:$VPS_PATH/.env
    scp docker-compose.yml $VPS_USER@$VPS_IP:$VPS_PATH/docker-compose.yml
#    scp db_init/init_db.sh $VPS_USER@$VPS_IP:$VPS_PATH/db_init/init_db.sh

    echo "✅ Directories and files setup completed"
}

copy_sql_files() {
    echo ""
    echo "📁 Copying SQL files on VPS..."

    # Копируем SQL файлы если они существуют
    scp db_init/zz_convert_charset.sql $VPS_USER@$VPS_IP:$VPS_PATH/db_init/zz_convert_charset.sql
    if ls db_init/sql/*.sql.gz 1> /dev/null 2>&1; then
        echo "📦 Copying SQL.gz files to VPS..."
#        scp db_init/sql/*.sql.gz $VPS_USER@$VPS_IP:$VPS_PATH/db_init/sql/
        rsync -avz --progress --partial db_init/sql/*.sql.gz $VPS_USER@$VPS_IP:$VPS_PATH/db_init/sql
    else
        echo "⚠️  No SQL.gz files found in db_init/sql/"
    fi

    echo "✅ SQL files setup completed"
}

extract_sql_files_on_vps() {
    echo ""
    echo "🗜️  Extracting SQL files on VPS..."

    ssh $VPS_USER@$VPS_IP << EOF
cd ~/$VPS_PATH

echo "📦 Extracting SQL.gz files in db_init/sql/..."
for gz_file in db_init/sql/*.sql.gz; do
    if [ -f "\$gz_file" ]; then
        filename=\$(basename "\$gz_file" .sql.gz)
        echo "Extracting \$gz_file -> db_init/\${filename}.sql"
        gunzip -c "\$gz_file" > "db_init/\${filename}.sql"
    fi
done

echo "✅ SQL files extracted on VPS"
EOF
}

reinitialize_database() {
    echo ""
    echo "🔄 Reinitializing database..."

    ssh $VPS_USER@$VPS_IP << EOF
cd ~/$VPS_PATH

echo "🗑️  Removing old database volume..."
#docker-compose down || true
docker-compose down -v || true

echo "🗜️  Extracting SQL files..."
for gz_file in db_init/sql/*.sql.gz; do
    if [ -f "\$gz_file" ]; then
        filename=\$(basename "\$gz_file" .sql.gz)
        echo "Extracting \$gz_file -> db_init/\${filename}.sql"
        gunzip -c "\$gz_file" > "db_init/\${filename}.sql"
    fi
done

echo "🚀 Starting fresh database..."
docker-compose up -d --force-recreate

echo "⏳ Waiting for database initialization..."
sleep 30

echo "✅ Database reinitialization completed"
EOF
}

copy_news_file() {
    echo ""
    echo "📰 Copying news file to VPS..."

    # Копируем файл на VPS
    scp ./data/bot_news.py $VPS_USER@$VPS_IP:$VPS_PATH/data/bot_news.py

    echo "✅ News file copied successfully"
}

setup_permissions() {
    echo ""
    echo "🔧 Setting permissions..."

    ssh $VPS_USER@$VPS_IP << EOF
cd ~/$VPS_PATH
#chmod +x db_init/init_db.sh
#chmod 755 data logs db_backups
EOF

    echo "✅ Permissions setup completed"
}

build_and_push_image() {
    echo ""
    echo "🚀 Building and pushing Docker image..."

    ssh $VPS_USER@$VPS_IP << EOF
cd ~/$VPS_PATH

echo "📥 Cloning latest code from GitHub..."
rm -rf temp_build
git clone $GITHUB_REPO --branch $BRANCH --single-branch temp_build

echo "🔐 Logging into Docker Hub..."
echo "$DOCKER_PASSWORD" | docker login -u "$DOCKER_USERNAME" --password-stdin

echo "🐳 Building Docker image..."
docker build -t $IMAGE_NAME:latest ./temp_build

echo "📤 Pushing to Docker Hub..."
docker push $IMAGE_NAME:latest

echo "🔐 Logging out from Docker Hub..."
docker logout

echo "🧹 Cleaning up temp files..."
rm -rf temp_build

echo "✅ Image build and push completed"
EOF
}

deploy_containers() {
    echo ""
    echo "🚀 Deploying containers..."

    ssh $VPS_USER@$VPS_IP << EOF
cd ~/$VPS_PATH

echo "🔄 Starting containers..."
docker-compose down || true
docker-compose pull
docker-compose up -d --force-recreate

echo "🧹 Cleaning up Docker..."
docker system prune -f

echo "✅ Container deployment completed"
EOF
}

check_status() {
    echo ""
    echo "🔍 Checking service status..."

    ssh $VPS_USER@$VPS_IP << EOF
cd ~/$VPS_PATH
sleep 10
docker-compose ps
echo ""
docker-compose logs --tail=15 mariadb
EOF

    echo "✅ Status check completed"
}

cleanup() {
    unset DOCKER_PASSWORD
    unset VPS_IP
    unset VPS_USER
}

# Обработка аргументов командной строки
case "${1:-}" in
    -u|--update)
        echo "🔄 Starting QUICK update..."
        prompt_user_input_vps
        deploy_containers
        check_status
        cleanup
        echo "✅ Quick update completed!"
        ;;

    -n|--news)
        prompt_user_input_vps
        copy_news_file
        ;;

    -d|--db-init)
        echo "🗜️  Starting database reinitialization..."
        prompt_user_input_vps
        reinitialize_database
        check_status
        cleanup
        echo "✅ Database reinitialization completed!"
        ;;

    -h|--help)
        show_usage
        ;;

    "")
        echo "🚀 Starting FULL deployment..."
        prompt_user_input_vps
        prompt_user_input_docker
        setup_directories_and_files
        copy_sql_files
        extract_sql_files_on_vps
        copy_news_file
        setup_permissions
        build_and_push_image
#        deploy_containers
#        check_status
        cleanup
        echo "✅ Full deployment completed!"
        ;;

    *)
        echo "Error: Unknown option $1"
        show_usage
        exit 1
        ;;
esac