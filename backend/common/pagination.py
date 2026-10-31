"""Standard pagination for Paint Shop Management System API.

Default page size: 25, max page size: 100.
Uses 'page' and 'page_size' query parameters.
"""

from rest_framework.pagination import PageNumberPagination


class StandardPagination(PageNumberPagination):
    """
    Standard page-number pagination with configurable page size.

    Query parameters:
        - page: Page number (default 1)
        - page_size: Number of items per page (default 25, max 100)
    """

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100
    page_query_param = "page"
