from datetime import datetime, timezone
import re
from typing import Protocol, Sequence
from sqlmodel import Session, col, desc, select
from sqlmodel.sql.expression import SelectOfScalar

from core.base.database.manager.connection import ConnectionDatabaseManager
from core.base.database.models.media import (
    Media,
    MediaCreate,
    MediaRead,
    MediaUpdate,
)
from core.base.database.utils.engine import manage_session
from exceptions import ItemNotFoundError
from app_logger import logger


class MediaUpdateProtocol(Protocol):
    @property
    def id(self) -> int: ...
    @property
    def monitor(self) -> bool: ...
    @property
    def trailer_exists(self) -> bool: ...
    @property
    def yt_id(self) -> str | None: ...
    @property
    def downloaded_at(self) -> datetime | None: ...


class MediaDatabaseManager:
    """
    Database manager for CRUD operations on Media objects.\n
    """

    __model_name = "Media"

    @manage_session
    def create_or_update_bulk(
        self,
        media_create_list: list[MediaCreate],
        *,
        _session: Session = None,  # type: ignore
    ) -> list[tuple[MediaRead, bool]]:
        """Create or update multiple media objects in the database at once. \n
        If media already exists, it will be updated, otherwise it will be created.\n
        Args:
            media_create_list (list[MediaCreate]): List of media objects to create or update.\n
            _session (Session) [Optional]: A session to use for the database connection.\n
                Default is None, in which case a new session will be created.\n
        Returns:
            list[tuple[MediaRead, bool]]: List of tuples with MediaRead objects and created flag.\n
            Example::\n
                [(<MediaRead obj 1>, True), (<MediaRead obj 2>, False), ...] \n
        Raises:
            ItemNotFoundError: If any of the connections with provided connection_id's are invalid.
            ValidationError: If any of the media items are invalid.
        """
        self._check_connection_exists_bulk(media_create_list, session=_session)
        db_media_list: list[tuple[Media, bool]] = []
        new_count: int = 0
        updated_count: int = 0
        for media_create in media_create_list:
            db_media, created, updated = self._create_or_update(media_create, _session)
            db_media_list.append((db_media, created))
            if created:
                new_count += 1
            if updated:
                updated_count += 1
        _session.commit()
        logger.info(
            f"{self.__model_name}: {new_count} Created, {updated_count} Updated."
        )
        return [
            (MediaRead.model_validate(db_media), created)
            for db_media, created in db_media_list
        ]

    @manage_session
    def read(
        self,
        id: int,
        *,
        _session: Session = None,  # type: ignore
    ) -> MediaRead:
        """Get a media object from the database by id.\n
        Args:
            id (int): The id of the media object to get.
            _session (Session) [Optional]: A session to use for the database connection.\n
                Default is None, in which case a new session will be created.\n
        Returns:
            MediaRead: The MediaRead object if it exists.
        Raises:
            ItemNotFoundError: If the media item with provided id doesn't exist.
        """
        db_media = self._get_db_item(id, _session)
        # Convert Media object to MediaRead object to return
        media_read = MediaRead.model_validate(db_media)
        return media_read

    @manage_session
    def read_all(
        self,
        movies_only: bool | None = None,
        *,
        _session: Session = None,  # type: ignore
    ) -> list[MediaRead]:
        """Get all media objects from the database.\n
        Args:
            movies_only (bool) [Optional]: Flag to get only movies. Default is None.\n
                If True, it will return only movies. If False, it will return only series.\n
                If None, it will return all media items.\n
            _session (Session) [Optional]: A session to use for the database connection.\n
                Default is None, in which case a new session will be created.\n
        Returns:
            list[MediaRead]: List of MediaRead objects.
        """
        statement = select(Media)
        if movies_only is not None:
            statement = statement.where(col(Media.is_movie).is_(movies_only))
        db_media_list = _session.exec(statement).all()
        return self._convert_to_read_list(db_media_list)

    @manage_session
    def read_all_by_connection(
        self,
        connection_id: int,
        *,
        _session: Session = None,  # type: ignore
    ) -> list[MediaRead]:
        """Get all media objects from the database for a given connection.\n
        Args:
            connection_id (int): The id of the connection to get media items for.
            _session (Session) [Optional]: A session to use for the database connection.\n
                Default is None, in which case a new session will be created.\n
        Returns:
            list[MediaRead]: List of MediaRead objects.
        """
        try:
            self._check_connection_exists(connection_id, session=_session)
        except ItemNotFoundError:
            logger.debug(
                f"Connection with id {connection_id} doesn't exist in the database."
                " Returning empty list."
            )
            return []
        statement = select(Media).where(Media.connection_id == connection_id)
        db_media_list = _session.exec(statement).all()
        return self._convert_to_read_list(db_media_list)

    @manage_session
    def read_recent(
        self,
        limit: int = 100,
        offset: int = 0,
        movies_only: bool | None = None,
        *,
        _session: Session = None,  # type: ignore
    ) -> list[MediaRead]:
        """Get the most recent media objects from the database.\n
        Args:
            limit (int) [Optional]: The number of recent media items to get. Max 100
            offset (int) [Optional]: The offset to start from. Default is 0.
            movies_only (bool) [Optional]: Flag to get only movies. Default is None.\n
                If True, it will return only movies. If False, it will return only series.\n
                If None, it will return all media items.\n
            _session (Session) [Optional]: A session to use for the database connection.\n
                Default is None, in which case a new session will be created.\n
        Returns:
            list[MediaRead]: List of MediaRead objects.
        """
        offset = max(0, offset)
        limit = max(1, min(limit, 100))
        statement = select(Media)
        if movies_only is not None:
            statement = statement.where(col(Media.is_movie).is_(movies_only))
        statement = statement.order_by(desc(Media.added_at)).offset(offset).limit(limit)
        db_media_list = _session.exec(statement).all()
        return self._convert_to_read_list(db_media_list)

    @manage_session
    def read_recently_downloaded(
        self,
        limit: int = 100,
        offset: int = 0,
        *,
        _session: Session = None,  # type: ignore
    ) -> list[MediaRead]:
        """Get the most recently downloaded media objects from the database.\n
        Args:
            limit (int) [Optional]: The number of recent media items to get. Max 100
            offset (int) [Optional]: The offset to start from. Default is 0.
            _session (Session) [Optional]: A session to use for the database connection.\n
                Default is None, in which case a new session will be created.\n
        Returns:
            list[MediaRead]: List of MediaRead objects.
        """
        offset = max(0, offset)
        limit = max(1, min(limit, 100))
        statement = (
            select(Media)
            .where(col(Media.downloaded_at).is_not(None))
            .order_by(desc(Media.downloaded_at))
            .offset(offset)
            .limit(limit)
        )
        db_media_list = _session.exec(statement).all()
        return self._convert_to_read_list(db_media_list)

    @manage_session
    def search(
        self,
        query: str,
        *,
        offset: int = 0,
        _session: Session = None,  # type: ignore
    ) -> list[MediaRead]:
        """Search for media objects in the database by `title`, `overview`, \
            `imdb id`, or `txdb id` [tmdb for `Movie`, tvdb for `Series`].\n
        If an exact match is found for `imdb id` or `txdb id`, it will return only that item.\n
        If a 4 digit number is found in the query, \
            it will only return list of media from that year [1900-2100].\n
        Otherwise, it will return a list of [max 50 recently added] Media matching the query.\n
        Args:
            query (str): The search query to search for in the media items.
            offset (int) [Optional]: The offset to start from. Default is 0.
            _session (Session) [Optional]: A session to use for the database connection.\n
                Default is None, in which case a new session will be created.\n
        Returns:
            list[MediaRead]: List of MediaRead objects.
        """
        offset = max(0, offset)
        limit = 50
        statement = self._get_search_statement(query, limit, offset)
        if statement is None:
            return []
        db_media_list = _session.exec(statement).all()
        # logger.info(f"Found {len(db_media_list)} media items.")
        return self._convert_to_read_list(db_media_list)

    @manage_session
    def update(
        self,
        media_id: int,
        media_update: MediaUpdate,
        *,
        _commit: bool = True,
        _session: Session = None,  # type: ignore
    ) -> None:
        """Update an existing media item in the database by id.\n
        Args:
            media_id (int): The id of the media to update.
            media_update (MediaUpdate): The media data to update.
            _commit (bool) [Optional]: Flag to `commit` the changes. Default is `True`.
            _session (Session) [Optional]: A session to use for the database connection. \
                Default is None, in which case a new session will be created. \n
        Returns:
            None
        Raises:
            ItemNotFoundError: If the media item with provided id doesn't exist.
        """
        db_media = self._get_db_item(media_id, _session)
        media_update_data = media_update.model_dump(
            exclude_unset=True,
            exclude_defaults=True,
            exclude_none=True,
            exclude={"youtube_trailer_id", "downloaded_at"},
        )
        db_media.sqlmodel_update(media_update_data)
        _session.add(db_media)
        if _commit:
            _session.commit()
        return

    @manage_session
    def update_bulk(
        self,
        media_updates: list[tuple[int, MediaUpdate]],
        *,
        _session: Session = None,  # type: ignore
    ) -> None:
        """Update multiple media items in the database at once.\n
        Args:
            media_updates (list[tuple[int, MediaUpdate]]): List of tuples with media id \
                and update data.\n
            _session (Session) [Optional]: A session to use for the database connection.\n
                Default is None, in which case a new session will be created.\n
        Returns:
            None
        Raises:
            ItemNotFoundError: If any of the media items with provided id's don't exist.
        """
        for media_id, media_update in media_updates:
            self.update(media_id, media_update, _session=_session, _commit=False)
        _session.commit()
        return

    @manage_session
    def update_media_status(
        self,
        media_update: MediaUpdateProtocol,
        *,
        _commit: bool = True,
        _session: Session = None,  # type: ignore
    ) -> None:
        """Update the monitoring status of a media item in the database by id.\n
        Args:
            media_update (MediaUpdateProtocol): The media update object satisfying the protocol.
            _commit (bool) [Optional]: Flag to `commit` the changes. Default is `True`.
            _session (Session) [Optional]: A session to use for the database connection. \
                Default is None, in which case a new session will be created.
        Returns:
            None
        Raises:
            ItemNotFoundError: If the media item with provided id doesn't exist.
        """
        db_media = self._get_db_item(media_update.id, _session)
        db_media.monitor = media_update.monitor
        db_media.trailer_exists = media_update.trailer_exists
        if media_update.downloaded_at:
            db_media.downloaded_at = media_update.downloaded_at
        if media_update.yt_id:
            db_media.youtube_trailer_id = media_update.yt_id
        _session.add(db_media)
        if _commit:
            _session.commit()
        return

    @manage_session
    def update_media_status_bulk(
        self,
        media_update_list: Sequence[MediaUpdateProtocol],
        *,
        _session: Session = None,  # type: ignore
    ) -> None:
        """Update the monitoring status of multiple media items in the database at once.\n
        Args:
            media_update_list (Sequence[MediaUpdateProtocol]): Sequence of media update objects.\n
            _session (Session) [Optional]: A session to use for the database connection.\n
                Default is None, in which case a new session will be created.
        Returns:
            None
        Raises:
            ItemNotFoundError: If any of the media items with provided id's don't exist.
        """
        for media_update in media_update_list:
            self.update_media_status(media_update, _session=_session, _commit=False)
        _session.commit()
        return

    @manage_session
    def delete(
        self,
        media_id: int,
        *,
        _session: Session = None,  # type: ignore
    ) -> None:
        """Delete a media item from the database by id.\n
        Args:
            media_id (int): The id of the media to delete.
            _session (Session) [Optional]: A session to use for the database connection.\
                Default is None, in which case a new session will be created.\n
        Returns:
            None
        Raises:
            ItemNotFoundError: If the media item with provided id doesn't exist.
        """
        db_media = self._get_db_item(media_id, _session)
        _session.delete(db_media)
        _session.commit()
        return

    @manage_session
    def delete_bulk(
        self,
        media_ids: list[int],
        *,
        _session: Session = None,  # type: ignore
    ) -> None:
        """Delete multiple media items from the database at once.\n
        Args:
            media_ids (list[int]): List of media id's to delete.
            _session (Session) [Optional]: A session to use for the database connection.\
                Default is None, in which case a new session will be created.\n
        Returns:
            None
        Raises:
            ItemNotFoundError: If any of the media items with provided id's don't exist.
        """
        for media_id in media_ids:
            try:
                media_db = self._get_db_item(media_id, _session)
                _session.delete(media_db)
            except ItemNotFoundError:
                logger.debug(
                    f"{self.__model_name} with id {media_id} doesn't exist in the database. "
                    "Skipping!"
                )
        _session.commit()
        return

    @manage_session
    def delete_except(
        self,
        connection_id: int,
        media_ids: list[int],
        *,
        _session: Session = None,  # type: ignore
    ) -> None:
        """Delete all media items from the database except the ones provided.\n
        Args:
            connection_id (int): The id of the connection to delete media items for.
            media_ids (list[int]): List of media id's to keep.
            _session (Session) [Optional]: A session to use for the database connection.\
                Default is None, in which case a new session will be created.\n
        Returns:
            None
        Raises:
            ItemNotFoundError: If any of the media items with provided id's don't exist.
        """
        statement = (
            select(Media)
            .where(Media.connection_id == connection_id)
            .where(~col(Media.id).in_(media_ids))
        )
        db_media_list = _session.exec(statement).all()
        for db_media in db_media_list:
            _session.delete(db_media)
        _session.commit()
        return

    def _create_or_update(
        self, media_create: MediaCreate, session: Session
    ) -> tuple[Media, bool, bool]:
        """🚨This is a private method🚨 \n
        Create or update a media in the database. \n
        If media already exists, it will be updated, otherwise it will be created.\n
        Does not commit the changes to database. Only adds to session.\n
        Args:
            media_create (MediaCreate): The media to create or update.
            _session (Session): A session to use for the database connection.\n
        Returns:
            tuple[Media, bool, bool]: Media object and flags indicating created and updated.\n
            Example::\n
                (<Media obj>, True)
        """
        db_media = self._read_if_exists(
            media_create.connection_id, media_create.txdb_id, session
        )
        if db_media:
            # Exists, update it
            media_update_data = media_create.model_dump(
                exclude_unset=True,
                # exclude_defaults=True,
                exclude_none=True,
                exclude={"youtube_trailer_id", "downloaded_at"},
            )
            db_media.sqlmodel_update(media_update_data)
            _updated = False
            if session.is_modified(db_media):
                db_media.updated_at = datetime.now(timezone.utc)
                _updated = True
            session.add(db_media)
            return db_media, False, _updated
        else:
            # Doesn't exist, Create it
            db_media = Media.model_validate(media_create)
            session.add(db_media)
            return db_media, True, False

    def _check_connection_exists(self, connection_id: int, session: Session) -> None:
        """🚨This is a private method🚨 \n
        Check if a connection exists in the database.\n
        Args:
            connection_id (int): The id of the connection to check.
            session (Session): A session to use for the database connection.\n
        Raises:
            ItemNotFoundError: If the connection with provided connection_id is invalid.
        """
        if not ConnectionDatabaseManager().check_if_exists(
            connection_id, _session=session
        ):
            raise ItemNotFoundError("Connection", connection_id)
        return

    def _check_connection_exists_bulk(
        self, media_items: list[MediaCreate], session: Session
    ) -> None:
        """🚨This is a private method🚨 \n
        Check if a connection exists in the database for multiple media items.\n
        Args:
            media_items (list[MediaCreate]): List of media items to check.
            session (Session): A session to use for the database connection.\n
        Raises:
            ItemNotFoundError: If any of the connections with provided connection_id's are invalid.
        """
        connection_ids = {media.connection_id for media in media_items}
        for connection_id in connection_ids:
            self._check_connection_exists(connection_id, session=session)
        return

    def _convert_to_read_list(self, db_media_list: Sequence[Media]) -> list[MediaRead]:
        """🚨This is a private method🚨 \n
        Convert a list of Media objects to a list of MediaRead objects.\n"""
        if not db_media_list or len(db_media_list) == 0:
            return []
        media_read_list: list[MediaRead] = []
        for db_media in db_media_list:
            media_read = MediaRead.model_validate(db_media)
            media_read_list.append(media_read)
        return media_read_list

    def _extract_four_digit_number(self, query: str) -> str | None:
        """🚨This is a private method🚨 \n
        Extract a 4 digit number from a string."""
        matches = re.findall(r"\b\d{4}\b", query)
        last_match = matches[-1] if matches else None
        return last_match

    def _extract_imdb_id(self, query: str) -> str | None:
        """🚨This is a private method🚨 \n
        Extract an imdb id from a string."""
        matches = re.findall(r"tt\d{7,}", query)
        last_match = matches[-1] if matches else None
        return last_match

    def _extract_txdb_id(self, query: str) -> str | None:
        """🚨This is a private method🚨 \n
        Extract a txdb id from a string.\n
        Series 5 digits -> tvdb id, Movie 6 digits -> tmdb id."""
        matches = re.findall(r"\b\d{5,6}\b", query)
        last_match = matches[-1] if matches else None
        return last_match

    def _get_txdb_statement(self, txdb_id: str) -> SelectOfScalar[Media]:
        """🚨This is a private method🚨 \n
        Get a statement for the database query with txdb id.\n"""
        statement = select(Media).where(Media.txdb_id == txdb_id)
        return statement

    def _get_imdb_statement(self, imdb_id: str) -> SelectOfScalar[Media]:
        """🚨This is a private method🚨 \n
        Get a statement for the database query with imdb id.\n"""
        statement = select(Media).where(Media.imdb_id == imdb_id)
        return statement

    def _get_year_statement(self, year: str) -> SelectOfScalar[Media]:
        """🚨This is a private method🚨 \n
        Get a statement for the database query with year.\n"""
        statement = select(Media).where(Media.year == year)
        return statement

    def _get_search_statement(
        self, query: str, limit: int = 50, offset: int = 0
    ) -> SelectOfScalar[Media] | None:
        """🚨This is a private method🚨 \n
        Get a search statement for the database query.\n"""
        # logger.info(f"Searching for: {query}")
        if not query:
            # logger.info("Empty query. Returning empty list.")
            return None
        imdb_id = self._extract_imdb_id(query)
        if imdb_id:
            # logger.info(f"Found imdb id: {imdb_id}")
            return self._get_imdb_statement(imdb_id)
        txdb_id = self._extract_txdb_id(query)
        if txdb_id:
            # logger.info(f"Found txdb id: {txdb_id}")
            return self._get_txdb_statement(txdb_id)
        # logger.info("No imdb or txdb id found. Building statement...")
        statement = select(Media)
        year = self._extract_four_digit_number(query)
        if year and int(year) > 1900 and int(year) < 2100:
            query = query.replace(year, "").strip().replace("  ", " ")
            statement = self._get_year_statement(year)
            # logger.info(f"Found year: {year}")

        statement = (
            statement.where(
                col(Media.title).ilike(f"%{query}%"),
                # or_(
                #     col(Media.title).ilike(f"%{query}%"),
                #     col(Media.overview).ilike(f"%{query}%"),
                # )
            )
            .offset(offset)
            .limit(limit)
            .order_by(desc(Media.added_at))
        )
        # logger.info(f"Final statement: {statement}")
        return statement

    def _get_db_item(self, media_id: int, session: Session) -> Media:
        """🚨This is a private method🚨 \n
        Get a media item from the database by id.\n
        Args:
            media_id (int): The id of the media item to get.
            session (Session): A session to use for the database connection.\n
        Returns:
            Media: The media object if it exists.
        Raises:
            ItemNotFoundError: If the media item with provided id doesn't exist.
        """
        db_media = session.get(Media, media_id)
        if not db_media:
            raise ItemNotFoundError(self.__model_name, media_id)
        return db_media

    def _read_if_exists(
        self,
        connection_id: int,
        txdb_id: str,
        session: Session,
    ) -> Media | None:
        """🚨This is a private method🚨 \n
        Check if a media item exists in the database for any given connection and arr ids.\n
        Args:
            connection_id (int): The id of the connection to check.
            txdb_id (str): The txdb id of the media item to check.
            session (Session): A session to use for the database connection.\n
        Returns:
            Media | None: The media object if it exists, otherwise None.
        """
        statement = (
            select(Media)
            .where(Media.connection_id == connection_id)
            .where(Media.txdb_id == txdb_id)
        )
        db_media = session.exec(statement).first()
        return db_media
