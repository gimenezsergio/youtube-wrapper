from datetime import datetime, timezone


def get_utc_now_iso():
    """Retorna la fecha y hora UTC actual en formato ISO 8601."""
    return datetime.now(timezone.utc).isoformat()

class CategoryRepository:
    @staticmethod
    def list_all(db) -> list[dict]:
        """Obtiene todas las categorías ordenadas por posición con sus palabras clave y cantidad de canales."""
        cursor = db.execute("""
            SELECT c.id, c.name, c.description, c.position, c.created_at, c.updated_at,
                   COALESCE(cc.channel_count, 0) as channelCount
            FROM categories c
            LEFT JOIN (
                SELECT category_id, COUNT(channel_id) as channel_count
                FROM channel_categories
                GROUP BY category_id
            ) cc ON c.id = cc.category_id
            ORDER BY c.position ASC
        """)
        categories = []
        for row in cursor.fetchall():
            cat = dict(row)
            # Obtener palabras clave asociadas
            keywords_cursor = db.execute("""
                SELECT term, polarity, weight
                FROM category_keywords
                WHERE category_id = ?
            """, (cat["id"],))
            cat["keywords"] = [dict(kw) for kw in keywords_cursor.fetchall()]
            categories.append(cat)
        return categories

    @staticmethod
    def get_by_id(db, category_id: int) -> dict | None:
        """Obtiene una categoría específica con sus palabras clave y cantidad de canales."""
        cursor = db.execute("""
            SELECT c.id, c.name, c.description, c.position, c.created_at, c.updated_at,
                   COALESCE(cc.channel_count, 0) as channelCount
            FROM categories c
            LEFT JOIN (
                SELECT category_id, COUNT(channel_id) as channel_count
                FROM channel_categories
                GROUP BY category_id
            ) cc ON c.id = cc.category_id
            WHERE c.id = ?
        """, (category_id,))
        row = cursor.fetchone()
        if not row:
            return None

        cat = dict(row)
        keywords_cursor = db.execute("""
            SELECT term, polarity, weight
            FROM category_keywords
            WHERE category_id = ?
        """, (category_id,))
        cat["keywords"] = [dict(kw) for kw in keywords_cursor.fetchall()]
        return cat

    @staticmethod
    def create(db, name: str, description: str = None, keywords: list[dict] = None) -> dict:
        """Crea una nueva categoría e inserta sus palabras clave dentro de una transacción."""
        normalized = name.strip().lower()
        if not normalized:
            raise ValueError("El nombre de la categoría no puede estar vacío.")

        # Verificar unicidad (case-insensitive)
        cursor = db.execute("SELECT 1 FROM categories WHERE normalized_name = ?", (normalized,))
        if cursor.fetchone():
            raise ValueError(f"Ya existe una categoría con el nombre '{name}'.")

        now = get_utc_now_iso()

        # Calcular siguiente posición
        pos_cursor = db.execute("SELECT COALESCE(MAX(position), 0) + 1 as next_pos FROM categories")
        position = pos_cursor.fetchone()["next_pos"]

        # Insertar categoría
        cursor = db.execute("""
            INSERT INTO categories (name, normalized_name, description, position, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (name.strip(), normalized, description, position, now, now))
        category_id = cursor.lastrowid

        # Insertar palabras clave
        if keywords:
            for kw in keywords:
                term = kw.get("term", "").strip()
                polarity = kw.get("polarity", "positive")
                weight = float(kw.get("weight", 1.0))
                if term:
                    db.execute("""
                        INSERT INTO category_keywords (category_id, term, weight, polarity)
                        VALUES (?, ?, ?, ?)
                    """, (category_id, term, weight, polarity))

        db.commit()
        return CategoryRepository.get_by_id(db, category_id)

    @staticmethod
    def update(db, category_id: int, name: str, description: str = None, keywords: list[dict] = None) -> dict:
        """Actualiza una categoría existente y sus palabras clave dentro de una transacción."""
        normalized = name.strip().lower()
        if not normalized:
            raise ValueError("El nombre de la categoría no puede estar vacío.")

        # Verificar existencia
        cursor = db.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,))
        if not cursor.fetchone():
            return None

        # Verificar unicidad contra otras categorías
        cursor = db.execute("SELECT 1 FROM categories WHERE normalized_name = ? AND id != ?", (normalized, category_id))
        if cursor.fetchone():
            raise ValueError(f"Ya existe otra categoría con el nombre '{name}'.")

        now = get_utc_now_iso()

        # Actualizar datos principales
        db.execute("""
            UPDATE categories
            SET name = ?, normalized_name = ?, description = ?, updated_at = ?
            WHERE id = ?
        """, (name.strip(), normalized, description, now, category_id))

        # Reemplazar palabras clave (borrado y reinserción)
        db.execute("DELETE FROM category_keywords WHERE category_id = ?", (category_id,))

        if keywords:
            for kw in keywords:
                term = kw.get("term", "").strip()
                polarity = kw.get("polarity", "positive")
                weight = float(kw.get("weight", 1.0))
                if term:
                    db.execute("""
                        INSERT INTO category_keywords (category_id, term, weight, polarity)
                        VALUES (?, ?, ?, ?)
                    """, (category_id, term, weight, polarity))

        db.commit()
        return CategoryRepository.get_by_id(db, category_id)

    @staticmethod
    def delete(db, category_id: int) -> bool:
        """Elimina una categoría. SQLite ON DELETE CASCADE limpia relaciones automáticamente."""
        cursor = db.execute("SELECT 1 FROM categories WHERE id = ?", (category_id,))
        if not cursor.fetchone():
            return False

        db.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        db.commit()
        return True

    @staticmethod
    def reorder(db, category_ids: list[int]) -> None:
        """Reordena atómicamente una lista de categorías asignándoles nuevas posiciones consecutivas."""
        for position, category_id in enumerate(category_ids, start=1):
            db.execute("""
                UPDATE categories
                SET position = ?, updated_at = ?
                WHERE id = ?
            """, (position, get_utc_now_iso(), category_id))
        db.commit()
