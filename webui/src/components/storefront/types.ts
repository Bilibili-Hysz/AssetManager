import type { ReactNode } from 'react';

export interface StorefrontProduct {
  id: string;
  slug?: string;
  name: string;
  description?: string;
  imageUrl: string;
  gallery?: string[];
  category?: string;
  tags?: string[];
  price: number;
  currency?: string;
  license?: string;
  downloads?: number;
  featured?: boolean;
  status?: 'active' | 'draft' | 'archived';
  updatedAt?: string;
}

export interface StorefrontCategory {
  id: string;
  name: string;
  count?: number;
  imageUrl?: string;
}

export interface StorefrontOrder {
  id: string;
  productName: string;
  productImageUrl?: string;
  amount: number;
  currency?: string;
  status: 'paid' | 'pending' | 'refunded' | 'failed';
  sourceStatus?: 'pending' | 'confirmed' | 'fulfilled' | 'revoked';
  createdAt: string;
}

export interface StorefrontStats {
  revenue: number;
  orders: number;
  products: number;
  views?: number;
}

export interface StorefrontData {
  name: string;
  tagline?: string;
  description?: string;
  logoUrl?: string;
  coverUrl?: string;
  accent?: string;
  products: StorefrontProduct[];
  categories?: StorefrontCategory[];
}

export interface SellerProfile {
  displayName: string;
  email?: string;
  avatarUrl?: string;
  storeName?: string;
  verified?: boolean;
}

export interface SellerPageProps {
  seller?: SellerProfile;
  products?: StorefrontProduct[];
  orders?: StorefrontOrder[];
  stats?: StorefrontStats;
  onNavigate?: (path: string) => void;
  children?: ReactNode;
}

export const formatMoney = (amount: number, currency = 'USD') =>
  new Intl.NumberFormat(undefined, { style: 'currency', currency, maximumFractionDigits: 2 }).format(amount);
