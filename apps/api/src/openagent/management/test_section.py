        query: str = "",
        scope: Optional[str] = None,
        memory_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        agent_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
        task_id: Optional[UUID] = None,
        conversation_id: Optional[UUID] = None,
        team_id: Optional[UUID] = None,
        scope_filter: Optional[str] = None,
        memory_type_filter: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
        use_vector_search: bool = True,
        query_embedding: Optional[List[float]] = None,
        similarity_threshold: float = 0.7,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Memory]:
        """Hybrid search combining keyword and vector search."""
        # Build query conditions
        conditions = [
            "m.organization_id = :org_id",
            "m.status = 'active'",
            "m.deleted_at IS NULL"
        ]
        params = {"org_id": str(organization_id), "limit": limit, "offset": offset}

        # Add keyword search
        if query:
            conditions.append("m.content ILIKE :query")
