import { PrismaClient, Prisma } from '@prisma/client';
import { BaseRepository, PaginationParams, PaginatedResult } from '../repository.js';
import type { OrganizationId, UserId } from '@openagent/types';

export interface CreateOrganizationData {
  name: string;
  slug: string;
  description?: string;
  avatar_url?: string;
  settings?: Record<string, unknown>;
}

export interface UpdateOrganizationData {
  name?: string;
  description?: string;
  avatar_url?: string;
  settings?: Record<string, unknown>;
}

export interface OrganizationWithMemberships {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  avatar_url: string | null;
  settings: Prisma.JsonValue;
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
    user: {
      id: string;
      email: string;
      name: string | null;
      avatar_url: string | null;
      is_active: boolean;
      is_superadmin: boolean;
      created_at: Date;
      updated_at: Date;
      deleted_at: Date | null;
    };
  }>;
}

export class OrganizationRepository extends BaseRepository<any, CreateOrganizationData, UpdateOrganizationData, any> {
  protected readonly model = 'organization' as any;

  constructor(prisma: PrismaClient) {
    super(prisma);
  }

  async findBySlug(slug: string): Promise<any | null> {
    return this.prisma.organization.findUnique({ where: { slug } });
  }

  async findByIdWithMemberships(id: OrganizationId): Promise<OrganizationWithMemberships | null> {
    const org = await this.prisma.organization.findUnique({
      where: { id },
      include: {
        memberships: {
          include: { user: true },
          where: { user: { deleted_at: null } },
        },
      },
    });
    return org as OrganizationWithMemberships | null;
  }

  async findByUser(userId: UserId, params: PaginationParams): Promise<PaginatedResult<OrganizationWithMemberships>> {
    const where = {
      memberships: { some: { user_id: userId } },
      deleted_at: null,
    };

    const [data, totalItems] = await Promise.all([
      this.prisma.organization.findMany({
        where,
        include: {
          memberships: {
            include: { user: true },
            where: { user_id: userId },
          },
        },
      } as any),
      this.prisma.organization.count({ where } as any),
    ]);

    const page = Math.max(1, params.page);
    const pageSize = Math.min(100, Math.max(1, params.pageSize));
    const totalPages = Math.ceil(totalItems / pageSize);

    return {
      data: data as OrganizationWithMemberships[],
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

  async createWithOwner(
    orgData: CreateOrganizationData,
    ownerId: UserId
  ): Promise<OrganizationWithMemberships> {
    return this.prisma.$transaction(async (tx: Prisma.TransactionClient) => {
      const organization = await tx.organization.create({ data: orgData as any });
      await tx.membership.create({
        data: {
          user_id: ownerId,
          organization_id: organization.id,
          role: 'owner',
        },
      });
      return this.findByIdWithMemberships(organization.id as OrganizationId) as Promise<OrganizationWithMemberships>;
    });
  }

  async addMember(
    organizationId: OrganizationId,
    userId: UserId,
    role: string = 'member'
  ): Promise<any> {
    return this.prisma.membership.create({
      data: {
        user_id: userId,
        organization_id: organizationId,
        role,
      },
    });
  }

  async removeMember(organizationId: OrganizationId, userId: UserId): Promise<void> {
    await this.prisma.membership.delete({
      where: {
        user_id_organization_id: { user_id: userId, organization_id: organizationId },
      },
    });
  }

  async updateMemberRole(
    organizationId: OrganizationId,
    userId: UserId,
    role: string
  ): Promise<any> {
    return this.prisma.membership.update({
      where: {
        user_id_organization_id: { user_id: userId, organization_id: organizationId },
      },
      data: { role },
    });
  }

  async getUserRole(organizationId: OrganizationId, userId: UserId): Promise<string | null> {
    const membership = await this.prisma.membership.findUnique({
      where: { user_id_organization_id: { user_id: userId, organization_id: organizationId } },
    });
    return membership?.role ?? null;
  }

  async isMember(organizationId: OrganizationId, userId: UserId): Promise<boolean> {
    const membership = await this.prisma.membership.findUnique({
      where: { user_id_organization_id: { user_id: userId, organization_id: organizationId } },
    });
    return !!membership;
  }

  async isOwnerOrAdmin(organizationId: OrganizationId, userId: UserId): Promise<boolean> {
    const role = await this.getUserRole(organizationId, userId);
    return role === 'owner' || role === 'admin';
  }
}