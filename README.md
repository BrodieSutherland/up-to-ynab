# UP to YNAB Transaction Sync

Automatically sync transactions from [Up Bank](https://up.com.au/) to [YNAB](https://www.youneedabudget.com/) using webhooks and APIs.

[![CI](https://github.com/brodie/up-to-ynab/actions/workflows/ci.yml/badge.svg)](https://github.com/brodie/up-to-ynab/actions/workflows/ci.yml)
[![Docker](https://img.shields.io/docker/v/username/up-to-ynab?label=docker)](https://hub.docker.com/r/username/up-to-ynab)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)

## Features

- 🔄 **Real-time sync** via Up Bank webhooks
- 🏷️ **Smart categorization** based on historical payee mappings
- 🚫 **Transfer filtering** to avoid duplicate internal transfers
- 📊 **Health monitoring** with built-in endpoints
- 🐳 **Docker ready** with production and development configurations
- 🧪 **Comprehensive testing** with >90% coverage
- 🔒 **Security focused** with non-root containers and vulnerability scanning

## Quick Start

### Prerequisites

- Up Bank API token ([get one here](https://developer.up.com.au/))
- YNAB Personal Access Token ([get one here](https://app.youneedabudget.com/settings/developer))
- YNAB Budget ID and Account ID
- Public webhook URL (for receiving Up Bank notifications)

### Docker Deployment (Recommended)

1. **Clone and setup:**
   ```bash
   git clone https://github.com/brodie/up-to-ynab.git
   cd up-to-ynab
   cp .env.example .env
   ```

2. **Configure environment variables in `.env`:**
   ```bash
   UP_API_TOKEN=your_up_api_token_here
   YNAB_API_TOKEN=your_ynab_token_here
   YNAB_BUDGET_ID=your_budget_id_here
   YNAB_ACCOUNT_ID=your_account_id_here
   WEBHOOK_URL=https://your-domain.com/webhook
   ```

   **⚠️ Important:** All API tokens are required for the application to function properly. The application will show configuration errors if tokens are missing or invalid.

3. **Start production environment:**
   ```bash
   ./scripts/start-prod.sh
   ```

The application will be available at `http://localhost:5001`.

### Development Setup

1. **Start development environment:**
   ```bash
   ./scripts/start-dev.sh
   ```

2. **Run tests:**
   ```bash
   ./scripts/run-tests.sh
   ```

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `UP_API_TOKEN` | ✅ | - | Up Bank API token |
| `YNAB_API_TOKEN` | ✅ | - | YNAB Personal Access Token |
| `YNAB_BUDGET_ID` | ✅ | - | YNAB Budget ID |
| `YNAB_ACCOUNT_ID` | ✅ | - | YNAB Account ID to sync to |
| `WEBHOOK_URL` | ❌ | - | Public URL for Up Bank webhooks |
| `PORT` | ❌ | 5001 | Server port |
| `DEBUG_MODE` | ❌ | false | Enable debug logging |
| `DATABASE_URL` | ❌ | sqlite:///./up_to_ynab.db | Database connection URL |

### Transfer Filtering

The following transaction descriptions are automatically filtered out as internal transfers:
- "Transfer to "
- "Cover to "
- "Quick save transfer to "
- "Forward to "

## API Endpoints

- `GET /health` - Health check endpoint
- `POST /webhook` - Up Bank webhook receiver
- `GET /refresh` - Manually refresh category mappings
- `GET /docs` - Interactive API documentation

## Architecture

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Up Bank   │───▶│  Webhook    │───▶│    YNAB     │
│             │    │  Processor  │    │             │
└─────────────┘    └─────────────┘    └─────────────┘
                          │
                          ▼
                   ┌─────────────┐
                   │  Category   │
                   │  Database   │
                   └─────────────┘
```

## Deployment Options

### Docker Compose (Production)
```bash
docker-compose up -d
```

### Docker Compose (Development)
```bash
docker-compose -f docker-compose.dev.yml up -d
```

### Manual Installation
```bash
# Install dependencies
pip install -r requirements.txt

# Run application
python -m uvicorn app:app --host 0.0.0.0 --port 5001
```

## Monitoring

### Health Checks
- **Endpoint:** `GET /health`
- **Response:** JSON with service status and version

### Logging
- Structured JSON logging in production
- Colored console logging in development
- Configurable log levels via `DEBUG_MODE`

### Docker Health Checks
Built-in Docker health checks monitor service availability every 30 seconds.

## Development

### Project Structure
```
refactor/
├── app.py                 # FastAPI application
├── models/               # Pydantic data models
├── services/            # Business logic services
├── database/           # Database models and connection
├── utils/             # Configuration and utilities
├── tests/            # Comprehensive test suite
└── scripts/         # Deployment and utility scripts
```

### Testing
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Run specific test file
pytest tests/test_transaction_service.py -v
```

### Code Quality
```bash
# Format code
black .

# Sort imports
isort .

# Lint code
flake8 .
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Security

- Non-root Docker containers
- Automated vulnerability scanning with Trivy
- Secure API token handling
- Input validation with Pydantic
- No secrets in logs or error messages

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

- 📖 [Documentation](https://github.com/brodie/up-to-ynab/wiki)
- 🐛 [Issue Tracker](https://github.com/brodie/up-to-ynab/issues)
- 💬 [Discussions](https://github.com/brodie/up-to-ynab/discussions)