"""CloudNova - Portal Corporativo Seguro (Flask + Entra ID + Azure SQL + Blob)."""
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from functools import wraps

import msal
from flask import Flask, redirect, render_template_string, request, session, url_for

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-me")

TENANT_ID = os.environ.get("TENANT_ID", "")
CLIENT_ID = os.environ.get("CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SQL_CONN = os.environ.get("SQL_CONN", "")
STORAGE_CONN = os.environ.get("STORAGE_CONN", "")
BLOB_CONTAINER = os.environ.get("BLOB_CONTAINER", "ficheiros")

PAGE = """<!doctype html>
<html lang="pt"><head><meta charset="utf-8"><title>CloudNova Portal</title>
<style>
body{font-family:Segoe UI,Arial,sans-serif;max-width:860px;margin:40px auto;padding:0 16px;color:#1b1b1b}
header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #ddd;padding-bottom:12px}
nav a{margin-right:14px}
.box{background:#f4f7fb;border:1px solid #d6e0ee;border-radius:8px;padding:16px;margin-top:20px}
.ok{color:#107c10;font-weight:bold}.err{color:#c50f1f;font-weight:bold}
table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:6px;text-align:left}
code{background:#eee;padding:2px 4px}
</style></head><body>
<header><h1>CloudNova Portal</h1>
{% if user %}<div>Sess&atilde;o: <b>{{ user.get('name') }}</b> ({{ user.get('preferred_username') }})
 &middot; <a href="{{ url_for('logout') }}">Sair</a></div>{% endif %}</header>
{% if user %}
<nav class="box"><a href="{{ url_for('index') }}">In&iacute;cio</a>
<a href="{{ url_for('db_test') }}">Teste base de dados</a>
<a href="{{ url_for('upload_test') }}">Teste Storage</a>
<a href="{{ url_for('egress_test') }}">Teste Firewall (egress)</a></nav>
{% else %}
<div class="box">
<p>Portal interno. &Eacute; necess&aacute;rio iniciar sess&atilde;o com a conta da organiza&ccedil;&atilde;o.</p>
<p><a href="{{ url_for('login') }}"><b>Entrar com Microsoft Entra ID</b></a></p></div>
{% endif %}
{% if titulo %}<div class="box"><h2>{{ titulo }}</h2>
{% if erro %}<p class="err">{{ erro }}</p>{% endif %}
{% if mensagem %}<p class="ok">{{ mensagem }}</p>{% endif %}
{% if linhas %}<table><tr>{% for c in colunas %}<th>{{ c }}</th>{% endfor %}</tr>
{% for l in linhas %}<tr>{% for v in l %}<td>{{ v }}</td>{% endfor %}</tr>{% endfor %}
</table>{% endif %}
</div>{% endif %}
<p style="margin-top:30px;color:#777;font-size:12px">Contentor: {{ host }} &middot; {{ agora }}</p>
</body></html>"""


def render(**kwargs):
    base = dict(user=session.get("user"), titulo=None, erro=None, mensagem=None,
                linhas=None, colunas=None, host=os.environ.get("HOSTNAME", "local"),
                agora=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))
    base.update(kwargs)
    return render_template_string(PAGE, **base)


def msal_app():
    return msal.ConfidentialClientApplication(
        CLIENT_ID, authority=AUTHORITY, client_credential=CLIENT_SECRET)


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapper


@app.route("/")
def index():
    return render()


@app.route("/health")
def health():
    return {"status": "ok"}


@app.route("/login")
def login():
    flow = msal_app().initiate_auth_code_flow(
        [], redirect_uri=url_for("authorized", _external=True))
    session["flow"] = flow
    return redirect(flow["auth_uri"])


@app.route("/getAToken")
def authorized():
    try:
        result = msal_app().acquire_token_by_auth_code_flow(session.get("flow", {}), request.args)
    except ValueError:
        return redirect(url_for("index"))
    if "error" in result:
        return render(titulo="Erro no login", erro=result.get("error_description", result["error"]))
    session.pop("flow", None)
    session["user"] = result.get("id_token_claims")
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    destino = urllib.parse.quote(url_for("index", _external=True), safe="")
    return redirect(f"{AUTHORITY}/oauth2/v2.0/logout?post_logout_redirect_uri={destino}")


@app.route("/db")
@login_required
def db_test():
    nome = session["user"].get("preferred_username", "desconhecido")
    try:
        import pyodbc
        conn = pyodbc.connect(SQL_CONN, timeout=30)
        cur = conn.cursor()
        cur.execute(
            "IF OBJECT_ID('dbo.visitas','U') IS NULL "
            "CREATE TABLE dbo.visitas (id INT IDENTITY PRIMARY KEY, "
            "utilizador NVARCHAR(200), data_hora DATETIME2 DEFAULT SYSUTCDATETIME())")
        cur.execute("INSERT INTO dbo.visitas (utilizador) VALUES (?)", nome)
        conn.commit()
        cur.execute("SELECT TOP 5 id, utilizador, data_hora FROM dbo.visitas ORDER BY id DESC")
        linhas = [tuple(r) for r in cur.fetchall()]
        cur.execute("SELECT @@SERVERNAME, DB_NAME()")
        servidor, base = cur.fetchone()
        conn.close()
        return render(titulo="Teste base de dados (Azure SQL via Private Endpoint)",
                      mensagem=f"Ligado a {servidor}/{base}. Registo inserido para {nome}.",
                      colunas=["id", "utilizador", "data_hora (UTC)"], linhas=linhas)
    except Exception as exc:  # mostra o erro para diagnostico
        return render(titulo="Teste base de dados", erro=f"Falha: {exc}")


@app.route("/upload")
@login_required
def upload_test():
    nome = session["user"].get("preferred_username", "desconhecido")
    try:
        from azure.storage.blob import BlobServiceClient
        cont = BlobServiceClient.from_connection_string(STORAGE_CONN).get_container_client(BLOB_CONTAINER)
        if not cont.exists():
            cont.create_container()
        blob = f"documento-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.txt"
        cont.upload_blob(blob, f"Ficheiro da empresa criado por {nome} no CloudNova.\n".encode("utf-8"))
        linhas = [(b.name, b.size, b.last_modified) for b in cont.list_blobs()]
        return render(titulo="Teste Storage (Blob via Private Endpoint)",
                      mensagem=f"Ficheiro '{blob}' guardado no contentor '{BLOB_CONTAINER}'.",
                      colunas=["ficheiro", "bytes", "modificado"], linhas=linhas)
    except Exception as exc:
        return render(titulo="Teste Storage", erro=f"Falha: {exc}")


def testar_url(url):
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            return ("PERMITIDO", f"HTTP {resp.status}")
    except urllib.error.HTTPError as exc:
        corpo = exc.read(200).decode("utf-8", "ignore").strip()
        if "Deny" in corpo or exc.code == 470:
            return ("BLOQUEADO", f"HTTP {exc.code}: {corpo}")
        return ("PERMITIDO", f"HTTP {exc.code}")
    except Exception as exc:
        return ("BLOQUEADO", f"{type(exc).__name__}: {exc}")


@app.route("/egress")
@login_required
def egress_test():
    destinos = ["https://login.microsoftonline.com", "http://www.google.com", "https://www.google.com"]
    linhas = [(d, *testar_url(d)) for d in destinos]
    return render(titulo="Teste de saida (egress) atraves do Azure Firewall",
                  mensagem="Apenas os destinos autorizados nas regras do Firewall devem estar PERMITIDOS.",
                  colunas=["destino", "resultado", "detalhe"], linhas=linhas)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
