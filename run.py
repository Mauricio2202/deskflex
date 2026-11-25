import os

from deskflex import create_app

app = create_app()

if __name__ == "__main__":
    # El depurador de Flask permite ejecutar código desde el navegador: solo se activa si lo pides (DESKFLEX_DEBUG=1).
    app.run(host="127.0.0.1", port=5000, debug=os.environ.get("DESKFLEX_DEBUG") == "1")
