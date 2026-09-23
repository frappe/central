import type { Component, Plugin, Ref } from 'vue'

export type ColorScheme = 'light' | 'dark' | 'system'
export type DropdownAlign = 'start' | 'center' | 'end'
export type DropdownSide = 'top' | 'right' | 'bottom' | 'left'

export interface DropdownOption {
	label?: string
	icon?: string | Component
	theme?: string
	disabled?: boolean
	selected?: boolean
	onClick?: () => void
	submenu?: DropdownOptions
}

export type DropdownOptions = DropdownOption[]

export interface UseCallOptions<TResponse, TParams> {
	url: string | Ref<string>
	method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
	params?: TParams | (() => TParams)
	immediate?: boolean
	refetch?: boolean
	staleOnError?: boolean
	initialData?: TResponse
	transform?: (data: TResponse) => TResponse
	onSuccess?: (data: TResponse) => void
	onError?: (error: Error) => void
}

export interface UseCallResult<TResponse, TParams> {
	data: TResponse | null
	error: unknown
	loading: boolean
	isFinished: boolean
	promise: Promise<void>
	submit: (params: TParams) => Promise<TResponse | null>
	reload: () => Promise<TResponse | null>
	abort: () => void
	reset: () => void
}

export function useCall<
	TResponse,
	TParams extends object | undefined = undefined,
>(
	options: UseCallOptions<TResponse, TParams>,
): UseCallResult<TResponse, TParams>

export type FilterValue =
	| string
	| number
	| boolean
	| [string, string | number | boolean | string[]]

export interface ListFilters {
	[field: string]: FilterValue | undefined
}

export interface UseListOptions<T> {
	doctype: string
	fields?: Array<keyof T | string>
	filters?: ListFilters | (() => ListFilters)
	orderBy?: string | (() => string)
	start?: number
	limit?: number
	immediate?: boolean
	refetch?: boolean
	staleOnError?: boolean
	initialData?: T[]
	transform?: (data: T[]) => T[]
	onSuccess?: (data: T[]) => void
	onError?: (error: Error) => void
}

export interface UseListResult<T extends { name: string }> {
	data: T[] | null
	error: unknown
	loading: boolean
	isFinished: boolean
	hasNextPage: boolean
	hasPreviousPage: boolean
	reload: () => Promise<unknown>
	next: () => void
	previous: () => void
	updateRow: (doc: Partial<T> & { name?: string }) => void
	removeRow: (name: string) => void
}

export function useList<T extends { name: string }>(
	options: UseListOptions<T>,
): UseListResult<T>

export interface UseDocOptions<T> {
	doctype: string
	name: string | Ref<string> | (() => string)
	immediate?: boolean
	staleOnError?: boolean
	transform?: (doc: T & { doctype: string }) => T & { doctype: string }
}

export interface UseDocResult<T> {
	doc: T | null
	error: unknown
	loading: boolean
	isFinished: boolean
	reload: () => Promise<void>
	setValue: {
		loading: boolean
		submit: (values: Partial<T>) => Promise<void>
	}
}

export function useDoc<T extends { name: string }>(
	options: UseDocOptions<T>,
): UseDocResult<T>

export function call<T>(method: string, params?: object): Promise<T>
export function frappeRequest<T>(options: {
	url: string
	method?: string
	params?: object
	body?: object
}): Promise<T>

export const dayjs: typeof import('dayjs').default
export const dayjsLocal: typeof import('dayjs').default
export const FrappeUI: Plugin
export function setConfig(key: string, value: unknown): void

export const toast: {
	success(message: string): void
	info(message: string): void
	error(message: string, options?: object): void
}

export function useColorScheme(): {
	colorScheme: Ref<ColorScheme>
	setColorScheme: (scheme: ColorScheme) => void
}

export interface ShortcutConfig {
	key: string
	ctrl?: boolean
	shift?: boolean
	alt?: boolean
	meta?: boolean
	description?: string
	group?: string
	allowInInput?: boolean
	allowInDialog?: boolean
	condition?: () => boolean
	handler?: () => void
}

export function useShortcut(
	config: ShortcutConfig & { handler: () => void },
): void
export function formatShortcutLabel(config: ShortcutConfig): string

export interface BreadcrumbItem {
	label: string
	route?: string | object
	[key: string]: unknown
}

export interface BreadcrumbsProps {
	items: BreadcrumbItem[]
}

export const Alert: Component
export const Avatar: Component
export const Badge: Component
export const BottomSheet: Component
export const Breadcrumbs: Component
export const Button: Component
export const Checkbox: Component
export const Combobox: Component
export const DateRangePicker: Component
export const DesktopShell: Component
export const Dialog: Component & {
	Title: Component
	Close: Component
}
export const Dropdown: Component
export const ErrorMessage: Component
export const FormControl: Component
export const KeyboardShortcut: Component
export const LoadingIndicator: Component
export const LoadingText: Component
export const MobileNav: Component
export const MobileNavItem: Component
export const MobileShell: Component
export const Popover: Component
export const Select: Component
export const SettingsBody: Component
export const SettingsContent: Component
export const SettingsDialog: Component
export const SettingsHeader: Component
export const SettingsNavGroup: Component
export const SettingsNavItem: Component
export const SettingsPanel: Component
export const SettingsRow: Component
export const SettingsSidebar: Component
export const Sidebar: Component
export const SidebarCollapseToggle: Component
export const SidebarHeader: Component
export const SidebarItem: Component
export const SidebarLabel: Component
export const Skeleton: Component
export const Slider: Component
export const Spinner: Component
export const Switch: Component
export const TabButtons: Component
export const Tabs: Component
export const TextInput: Component
export const ToastProvider: Component
export const Tooltip: Component
