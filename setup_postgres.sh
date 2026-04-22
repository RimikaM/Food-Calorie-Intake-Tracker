#!/bin/bash
# Setup PostgreSQL for local development

set -e

DB_NAME="${DB_NAME:-food_calorie_intake}"
DB_USER="${DB_USER:-food_calorie_user}"
DB_HOST="localhost"
DB_PORT="5432"

echo "🔧 Setting up PostgreSQL for Calorie Intake..."

# Check if PostgreSQL is running
if ! psql -h "$DB_HOST" -U "$DB_USER" -tc "SELECT 1" > /dev/null 2>&1; then
    echo "❌ PostgreSQL is not running or not accessible"
    echo "Start PostgreSQL and try again. On macOS with Homebrew:"
    echo "  brew services start postgresql"
    exit 1
fi

echo "✓ PostgreSQL is running"

# Create database if it doesn't exist
if psql -h "$DB_HOST" -U "$DB_USER" -tc "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | grep -q 1; then
    echo "⚠️  Database '$DB_NAME' already exists"
else
    echo "📦 Creating database '$DB_NAME'..."
    createdb -h "$DB_HOST" -U "$DB_USER" "$DB_NAME"
    echo "✓ Database created"
fi

# Build connection string
CONNECTION_STRING="postgresql://$DB_USER@$DB_HOST:$DB_PORT/$DB_NAME"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ PostgreSQL Setup Complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📌 Add this to your environment:"
echo ""
echo "export DATABASE_URL=\"$CONNECTION_STRING\""
echo ""
echo "Then run:"
echo "  python web_app.py"
echo ""
echo "To verify it's working:"
echo "  psql \"$CONNECTION_STRING\" -c \"SELECT version();\""
echo ""
