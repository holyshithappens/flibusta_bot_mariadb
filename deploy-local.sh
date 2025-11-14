#!/bin/bash
# deploy-local.sh - Локальное развертывание приложения

set -e

# Конфигурация
DOCKER_USERNAME="holyshithappens"
DOCKER_IMAGE_NAME="flbst-bot-mdb"
IMAGE_NAME="$DOCKER_USERNAME/$DOCKER_IMAGE_NAME"
GITHUB_REPO="https://github.com/holyshithappens/flibusta_bot_mariadb.git"
BRANCH="master"
PROJECT_DIR="."

# Функции
show_usage() {
    echo "Usage: $0 [OPTION]"
    echo "Local deployment script for Flibusta Bot"
    echo ""
    echo "Options:"
    echo "  -u, --update    Quick update (pull and restart containers)"
    echo "  -d, --db-init   Reinitialize database"
    echo "  -h, --help      Show this help message"
    echo ""
    echo "Without options: Full deployment (build and deploy)"
}

build_and_push_image() {
    echo "🚀 Building and pushing Docker image..."

    # Создаем временную директорию для сборки
    local temp_dir=$(mktemp -d)

    # Клонируем свежий код
    git clone "$GITHUB_REPO" --branch "$BRANCH" --single-branch --depth 1 "$temp_dir"

    # Логин в Docker Hub
    if ! docker login -u "$DOCKER_USERNAME"; then
        echo "❌ Docker login failed"
        rm -rf "$temp_dir"
        exit 1
    fi

    # Сборка и пуш образа
    docker build -t "$IMAGE_NAME:latest" "$temp_dir"
    docker push "$IMAGE_NAME:latest"
    docker logout

    # Очистка
    rm -rf "$temp_dir"
    echo "✅ Image build and push completed"
}

deploy_containers() {
    echo "🚀 Deploying containers..."

    cd "$PROJECT_DIR"
    docker-compose down || true
    docker-compose pull
    docker-compose up -d --force-recreate

    echo "✅ Container deployment completed"
}

reinitialize_database() {
    echo "🔄 Reinitializing database..."

    cd "$PROJECT_DIR"
    docker-compose down -v
    deploy_containers

    echo "⏳ Waiting for database initialization..."
    sleep 30
    echo "✅ Database reinitialization completed"
}

check_status() {
    echo "🔍 Checking service status..."

    cd "$PROJECT_DIR"
    sleep 10
    docker-compose ps
    echo ""
    docker-compose logs --tail=10 mariadb bot

    echo "✅ Status check completed"
}

cleanup_docker() {
    echo "🧹 Cleaning up Docker..."
    docker system prune -f
}

# Обработка аргументов
case "${1:-}" in
    -u|--update)
        echo "🔄 Starting QUICK update..."
        deploy_containers
        check_status
        echo "✅ Quick update completed!"
        ;;

    -d|--db-init)
        echo "🗜️ Starting database reinitialization..."
        reinitialize_database
        check_status
        echo "✅ Database reinitialization completed!"
        ;;

    -h|--help)
        show_usage
        ;;

    "")
        echo "🚀 Starting FULL deployment..."
        build_and_push_image
        deploy_containers
        check_status
        cleanup_docker
        echo "✅ Full deployment completed!"
        ;;

    *)
        echo "Error: Unknown option $1"
        show_usage
        exit 1
        ;;
esac