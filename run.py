from app import create_app

app = create_app()

if __name__ == "__main__":
    # Windows에서 Werkzeug 개발서버가 요청마다 클라이언트 IP의 역방향 DNS 조회를
    # 시도하면서 요청당 1~2초씩 지연되는 문제가 있어, 로그용 조회를 건너뛰도록 패치.
    from werkzeug.serving import WSGIRequestHandler

    WSGIRequestHandler.address_string = lambda self: self.client_address[0]

    app.run(debug=True, port=5001, threaded=True)
