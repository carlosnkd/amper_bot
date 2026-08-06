"""Tests for GET /items/{item_id}."""


def test_read_item_without_query(client):
    response = client.get("/items/1")

    assert response.status_code == 200
    assert response.json() == {"item_id": 1, "q": None}


def test_read_item_with_query(client):
    response = client.get("/items/2", params={"q": "hello"})

    assert response.status_code == 200
    assert response.json() == {"item_id": 2, "q": "hello"}


def test_read_item_unknown_id_returns_404(client):
    response = client.get("/items/99999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Item not found", "status_code": 404}


def test_read_item_non_integer_id_returns_422(client):
    response = client.get("/items/not-an-int")

    body = response.json()
    assert response.status_code == 422
    assert body["status_code"] == 422
    assert isinstance(body["detail"], list)
    assert any("item_id" in error["loc"] for error in body["detail"])


def test_read_item_over_length_query_returns_422(client):
    response = client.get("/items/1", params={"q": "x" * 51})

    body = response.json()
    assert response.status_code == 422
    assert body["status_code"] == 422
    assert any("q" in error["loc"] for error in body["detail"])


def test_read_item_max_length_query_is_accepted(client):
    query = "y" * 50
    response = client.get("/items/1", params={"q": query})

    assert response.status_code == 200
    assert response.json() == {"item_id": 1, "q": query}
