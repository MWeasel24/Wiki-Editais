from wikieditais.web import create_app
from wikieditais.config import config

app = create_app()

if __name__ == '__main__':
    app.run(host=config.data['app'].get('host','127.0.0.1'), port=int(config.data['app'].get('port',5000)), debug=bool(config.data['app'].get('debug',True)))
