import { PrismaClient, Prisma } from '@prisma/client';
import { BaseRepository, PaginationParams, PaginatedResult } from '../repository.js';
import type { UserId, OrganizationId } from '@openagent/types';

export interface CreateUserData {
  email: string;
  name?: string;
  avatar_url?: string;
  password_hash?: string;
  is_superadmin?: boolean;
}

export interface UpdateUserData {
  name?: string;
  avatar_url?: string;
  is_active?: boolean;
}

export interface UserWithMemberships {
  id: string;
  email: string;
  name: string | null;
  avatar_url: string | null;
  password_hash: string | null;
  is_active: boolean;
  is_superadmin: boolean;
  created_at: Date;
  updated_at: Date;
  deleted_at: Date | null;
  memberships: Array<{
    id: string;
    user_id: string;
    organization_id: string;
    role: string;
    created_at: Date;
    updated_at: Date;
    organization: {
      id: string;
      name: string;
      slug: string;
      description: string | null;
      avatar_url: string | null;
      settings: Prisma.JsonValue;
      created_at: Date;
      updated_at: Date;
      deleted_at: Date | null;
    };
  }>;
}

export class UserRepository extends BaseRepository<any, CreateUserData, UpdateUserData, any> {
  protected readonly model = 'user' as any;

  constructor(prisma: PrismaClient) {
    super(prisma);
  }

  async findByEmail(email: string): Promise<any | null> {
    return this.prisma.user.findUnique({ where: { email } });
  }

  async findByIdWithMemberships(id: UserId): Promise<UserWithMemberships | null> {
    const user = await this.prisma.user.findUnique({
      where: { id },
      include: {
        memberships: {
          include: { organization: true },
          where: { organization: { deleted_at: null } },
        },
      },
    });
    return user as UserWithMemberships | null;
  }

  async findByOrganization(
    organizationId: OrganizationId,
    params: PaginationParams
  ): Promise<PaginatedResult<UserWithMemberships>> {
    const where = {
      memberships: { some: { organization_id: organizationId } },
      deleted_at: null,
    };

    const [data, totalItems] = await Promise.all([
      this.prisma.user.findMany({
        where,
        include: {
          memberships: {
            include: { organization: true },
            where: { organization_id: organizationId },
          },
        },
      } as any),
      this.prisma.user.count({ where } as any),
    ]);

    const page = Math.max(1, params.page);
    const pageSize = Math.min(100, Math.max(1, params.pageSize));
    const totalPages = Math.ceil(totalItems / pageSize);

    return {
      data: data as UserWithMemberships[],
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

  async createWithMembership(
    userData: CreateUserData,
    organizationId: OrganizationId,
    role: string = 'member'
  ): Promise<UserWithMemberships> {
    return this.prisma.$transaction(async (tx: Prisma.TransactionClient) => {
      const user = await tx.user.create({ data: userData as any });
      await tx.membership.create({
        data: {
          user_id: user.id,
          organization_id: organizationId,
          role,
        },
      });
      return this.findByIdWithMemberships(user.id as UserId) as Promise<UserWithMemberships>;
    });
  }

  async updateLastActive(id: UserId): Promise<void> {
    await this.prisma.user.update({
      where: { id },
      data: { updated_at: new Date() },
    });
  }
}