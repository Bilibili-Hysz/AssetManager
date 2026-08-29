import contracts from '../../../tests/contracts/lan_public_contracts.json';
import { describe, expect, it } from 'vitest';
import type { GalleryEntry, InviteResponse, ProjectItem, ServerInfo, ShareInfoResponse, ShopBuyerOrder, ShopItem, ShopOrder, StatsResponse, Tag, TreeItem, UserResponse } from '../types/api';

describe('LAN public DTO contracts', () => {
  it('normalizes users and invites without repository fields', () => {
    expect(contracts.records.user).toMatchObject({ is_active: 1, password_hash: 'secret' });
    expect(contracts.records.invite_used).toMatchObject({ is_active: 1, created_by: 'owner' });
    const user = contracts.responses.user as UserResponse;
    const invite = contracts.responses.invite_used as InviteResponse;

    expect(user).toEqual({ id: 1, username: 'owner', role: 'admin', active: true, created_at: 100 });
    expect(invite).toEqual({ code: 'USED', created_at: 101, used_by: null, revoked: false });
    expect(user).not.toHaveProperty('is_active');
    expect(user).not.toHaveProperty('password_hash');
    expect(invite).not.toHaveProperty('is_active');
    expect(invite).not.toHaveProperty('created_by');
    expect(user.active).toBe(Boolean(contracts.records.user.is_active));
    expect(user.created_at).toBe(Number(contracts.records.user.created_at));
    expect(invite.revoked).toBe(!Boolean(contracts.records.invite_used.is_active));
    expect(invite.used_by).toBeNull();
  });

  it('normalizes tags, tree nodes, and stats', () => {
    const tag = contracts.responses.tag as Tag;
    const tree = contracts.responses.tree as TreeItem;
    const stats = contracts.responses.stats as StatsResponse;

    expect(tag).toEqual({ id: null, name: 'hero', count: 3 });
    expect(tree).toEqual({
      name: 'project', path: 'project', type: 'dir', is_leaf: false,
      children: [
        { name: 'assets', path: 'project/assets', type: 'dir', is_leaf: true, children: [] },
        { name: 'source', path: 'project/source', type: 'dir', is_leaf: true, children: [] },
      ],
    });
    expect(stats).toEqual(contracts.responses.stats);
    expect(tree).not.toHaveProperty('is_file');
    expect(stats).not.toHaveProperty('secret');
  });

  it('anchors the file-list item shape to the backend golden contract', () => {
    const item = contracts.responses.files_item as ProjectItem;

    // Every key the backend emits must be declared on ProjectItem; a drift
    // like a missing is_project (formerly only caught by a runtime probe in
    // BrowsePage) fails the type anchor here.
    expect(Object.keys(item).sort()).toEqual([
      'category', 'extension', 'is_project', 'modified', 'name', 'path',
      'size', 'size_fmt', 'thumbnail_url', 'type',
    ]);
    expect(item).toHaveProperty('is_project');
    expect(item.is_project).toBe(false);
    expect(item.type).toBe('file');
  });

  it('keeps the ServerInfo shape free of removed ghost fields', () => {
    // The info envelope is locked on the backend side (test_public_contracts);
    // here the frontend type must not carry fields the backend never sends.
    const info = contracts.responses.info as ServerInfo;
    expect(info).not.toHaveProperty('asset_root_id');
    expect(info).not.toHaveProperty('total_collections');
    expect(info).not.toHaveProperty('total_artworks');
    expect(info.library_stats).toEqual({ total_projects: 0, total_size: 0, total_size_fmt: '0 B' });
    expect(info.feature_flags).toEqual({ commerce: false, seller: false, quota: false });
    // Follow-the-owner identity (A1): theme_name is part of the locked
    // envelope and must stay declared on ServerInfo for the reverse direction.
    expect(info.theme_name).toBe('Navy');
  });

  it('anchors the shop item shape to the backend _public_item golden', () => {
    // ShopService._public_item normalizes paths, extracts gallery_paths from
    // metadata and derives status; the golden locks that exact conversion and
    // this anchors every emitted key on the frontend ShopItem type.
    const item = contracts.responses.shop_item as ShopItem;
    expect(Object.keys(item).sort()).toEqual([
      'cover_path', 'created_at', 'currency', 'description', 'enabled',
      'gallery_paths', 'id', 'metadata', 'path', 'price_cents', 'status',
      'title', 'updated_at',
    ]);
    expect(item.gallery_paths).toEqual(['packs/a.png', 'packs/b.png']);
    expect(item.path).toBe('packs/hero.zip');
    expect(item.status).toBe('active');
  });

  it('anchors buyer and seller order shapes to the backend order golden', () => {
    const buyer = contracts.responses.shop_buyer_order as ShopBuyerOrder;
    expect(Object.keys(buyer).sort()).toEqual([
      'amount_cents', 'created_at', 'currency', 'delivery_available',
      'id', 'item_id', 'item_title', 'quantity', 'status',
      'unit_price_cents', 'updated_at',
    ]);
    expect(buyer.delivery_available).toBe(true);
    expect(buyer.quantity).toBe(2);
    expect(buyer.unit_price_cents).toBe(625);

    const seller = contracts.responses.shop_seller_order as ShopOrder;
    expect(Object.keys(seller).sort()).toEqual([
      'amount_cents', 'buyer_email', 'buyer_name', 'created_at', 'currency',
      'id', 'item_id', 'item_path', 'item_title', 'metadata', 'status',
      'updated_at',
    ]);
    expect(seller).not.toHaveProperty('dropped_secret');
  });

  it('anchors share info expiry semantics and the gallery entry shape', () => {
    const share = contracts.responses.share_info as ShareInfoResponse;
    expect(share).toEqual({
      id: 'share-123', paths: ['projects/hero.png'], created_by: 'owner',
      created_at: 100, allow_preview: true, download_count: 2, max_downloads: 5,
      has_password: false, expired: false, expires_in_hours: null,
    });

    const expiring = contracts.responses.share_info_expiring as ShareInfoResponse;
    expect(expiring.expired).toBe(false);
    expect(expiring.expires_in_hours).toBe(2);
    expect(expiring.has_password).toBe(true);
    expect(expiring.max_downloads).toBeNull();

    const entry = contracts.responses.gallery_entry as GalleryEntry;
    const galleryKeys = Object.keys(entry).sort();
    expect(galleryKeys).toEqual([
      'artwork_count', 'aspect_ratio', 'child_count', 'cover_path', 'cover_url',
      'file_count', 'height', 'kind', 'modified', 'name', 'parent_path', 'path',
      'size', 'size_fmt', 'tags', 'width',
    ]);
    expect(entry.kind).toBe('project');
  });
});
