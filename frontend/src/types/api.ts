export interface ApiError {
  message: string;
  code?: string;
  status?: number;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
  page_size?: number;
  totalPages?: number;
  total_pages?: number;
  hasMore?: boolean;
}
