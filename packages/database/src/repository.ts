import { PrismaClient } from "@prisma/client";
import type { OrganizationId, UserId } from "@openagent/types";

export interface PaginationParams {
  page: number;
  pageSize: number;
}

export interface PaginatedResult<T> {
  data: T[];
  meta: {
    page: number;
    pageSize: number;
    totalItems: number;
    totalPages: number;
    hasNext: boolean;
    hasPrev: boolean;
  };
}

export abstract class BaseRepository<T, TCreate, TUpdate, TWhere> {
  protected abstract readonly model: any;

  constructor(protected readonly prisma: PrismaClient) {}

  protected async paginate<T>(
    findMany: () => Promise<T[]>,
    count: () => Promise<number>,
    params: PaginationParams,
  ): Promise<PaginatedResult<T>> {
    const page = Math.max(1, params.page);
    const pageSize = Math.min(100, Math.max(1, params.pageSize));
    const [data, totalItems] = await Promise.all([findMany(), count()]);
    const totalPages = Math.ceil(totalItems / pageSize);

    return {
      data,
      meta: {
        page,
        pageSize,
        totalItems,
        totalPages,
        hasNext: page < totalPages,
        hasPrev: page > 1,
      },
    };
  }

  async findById(id: string): Promise<T | null> {
    // @ts-expect-error - dynamic model access
    return this.prisma[this.model].findUnique({ where: { id } } as any);
  }

  async findMany(
    params: PaginationParams,
    where?: TWhere,
  ): Promise<PaginatedResult<T>> {
    return this.paginate(
      // @ts-expect-error - dynamic model access
      () => this.prisma[this.model].findMany({ where: where as any } as any),
      // @ts-expect-error - dynamic model access
      () => this.prisma[this.model].count({ where: where as any } as any),
      params,
    );
  }

  async create(data: TCreate): Promise<T> {
    // @ts-expect-error - dynamic model access
    return this.prisma[this.model].create({ data: data as any } as any);
  }

  async update(id: string, data: TUpdate): Promise<T> {
    // @ts-expect-error - dynamic model access
    return this.prisma[this.model].update({
      where: { id },
      data: data as any,
    } as any);
  }

  async delete(id: string): Promise<T> {
    // @ts-expect-error - dynamic model access
    return this.prisma[this.model].delete({ where: { id } } as any);
  }

  async softDelete(id: string): Promise<T> {
    // @ts-expect-error - dynamic model access
    return this.prisma[this.model].update({
      where: { id },
      data: { deleted_at: new Date() } as any,
    } as any);
  }
}

export function createOrganizationScope(organizationId: OrganizationId) {
  return { organization_id: organizationId };
}

export function createUserScope(userId: UserId) {
  return { user_id: userId };
}
