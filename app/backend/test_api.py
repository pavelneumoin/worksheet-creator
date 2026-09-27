"""Check local ListOK without reading or printing credentials."""
import requests


def main():
    response = requests.get('http://127.0.0.1:3005/api/status', timeout=10)
    response.raise_for_status()
    status = response.json()
    print('Model:', status.get('ai_model'))
    print('AI configured:', bool(status.get('ai_ready')))
    print('Local PDF compiler:', bool(status.get('latex_ready')))
    print('A photo request is required to verify access to the AI provider.')


if __name__ == '__main__':
    main()
