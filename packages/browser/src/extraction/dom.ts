import {
  BrowserObservation,
  InteractiveElement,
  AccessibilityNode,
  BoundingBox,
  BrowserExtractOptions,
} from '../core/types';
import type { BrowserPage, BrowserFrame } from '../providers/types';
import { createChildLogger } from '@openagent/logger';

const logger = createChildLogger({ module: 'browser:extraction' });

export interface DOMExtractionConfig {
  maxElements: number;
  maxTextLength: number;
  includeHidden: boolean;
  includeAttributes: string[];
  excludeSelectors: string[];
  interactiveRoles: string[];
  pruneThreshold: number;
}

export const defaultExtractionConfig: DOMExtractionConfig = {
  maxElements: 200,
  maxTextLength: 50000,
  includeHidden: false,
  includeAttributes: ['id', 'class', 'name', 'type', 'value', 'href', 'src', 'alt', 'title', 'role', 'aria-label', 'aria-labelledby', 'placeholder', 'data-testid'],
  excludeSelectors: ['script', 'style', 'noscript', 'iframe', 'head', 'meta', 'link'],
  interactiveRoles: ['button', 'link', 'textbox', 'checkbox', 'radio', 'combobox', 'listbox', 'menuitem', 'tab', 'slider', 'spinbutton', 'searchbox', 'option', 'treeitem'],
  pruneThreshold: 0.8,
};

export class DOMExtractor {
  private config: DOMExtractionConfig;

  constructor(config: Partial<DOMExtractionConfig> = {}) {
    this.config = { ...defaultExtractionConfig, ...config };
  }

  async extractObservation(page: BrowserPage, frame?: BrowserFrame, strategy: 'minimal' | 'standard' | 'detailed' | 'visual' = 'standard'): Promise<BrowserObservation> {
    const target = frame || page;
    
    const [url, title, viewport, scrollPosition, interactiveElements, textContent, domSnapshot, accessibilityTree, screenshot] = await Promise.all([
      this.getUrl(target),
      this.getTitle(target),
      this.getViewport(target),
      this.getScrollPosition(target),
      this.extractInteractiveElements(target),
      strategy !== 'minimal' ? this.extractTextContent(target) : Promise.resolve(undefined),
      strategy === 'detailed' ? this.extractDOMSnapshot(target) : Promise.resolve(undefined),
      strategy !== 'minimal' ? this.extractAccessibilityTree(target) : Promise.resolve(undefined),
      strategy === 'visual' ? this.extractScreenshot(target) : Promise.resolve(undefined),
    ]);

    return {
      url,
      title,
      viewport,
      scrollPosition,
      interactiveElements: this.pruneElements(interactiveElements),
      textContent,
      domSnapshot,
      screenshot,
      accessibilityTree,
      metadata: {
        extractionStrategy: strategy,
        elementCount: interactiveElements.length,
        timestamp: new Date().toISOString(),
      },
    };
  }

  private async getUrl(target: BrowserPage | BrowserFrame): Promise<string> {
    return target.url;
  }

  private async getTitle(target: BrowserPage | BrowserFrame): Promise<string> {
    if ('title' in target) {
      return target.title || '';
    }
    return target.evaluate(() => document.title) || '';
  }

  private async getViewport(target: BrowserPage | BrowserFrame): Promise<{ width: number; height: number }> {
    if ('viewport' in target) {
      const vp = target.viewport();
      return vp || { width: 1280, height: 720 };
    }
    return target.evaluate(() => ({ width: window.innerWidth, height: window.innerHeight }));
  }

  private async getScrollPosition(target: BrowserPage | BrowserFrame): Promise<{ x: number; y: number }> {
    return target.evaluate(() => ({ x: window.scrollX, y: window.scrollY }));
  }

  async extractInteractiveElements(target: BrowserPage | BrowserFrame): Promise<InteractiveElement[]> {
    // NOTE: the page function must be self-contained (no `this` capture):
    // providers serialize it into the page.
    const elements = await target.evaluate((config: DOMExtractionConfig) => {
      const { interactiveRoles, includeAttributes, excludeSelectors, maxElements, includeHidden } = config;

      const inferRole = (element: Element): string => {
        const tag = element.tagName.toLowerCase();
        const type = ((element as HTMLInputElement).type || '').toLowerCase();
        if (tag === 'a') return 'link';
        if (tag === 'button') return 'button';
        if (tag === 'input') return type === 'checkbox' ? 'checkbox' : type === 'radio' ? 'radio' : 'textbox';
        if (tag === 'textarea') return 'textbox';
        if (tag === 'select') return 'combobox';
        if (tag === 'option') return 'option';
        if (/^h[1-6]$/.test(tag)) return 'heading';
        if (tag === 'img') return 'img';
        if (tag === 'form') return 'form';
        return 'generic';
      };

      const selectorFor = (element: Element): string => {
        if (element.id) return `#${element.id}`;
        const testId = element.getAttribute('data-testid');
        if (testId) return `[data-testid="${testId}"]`;
        const name = element.getAttribute('name');
        if (name) return `[name="${name}"]`;
        return element.tagName.toLowerCase();
      };

      const excludeSelector = excludeSelectors.join(', ');
      const candidates = document.querySelectorAll('*');
      const results: InteractiveElement[] = [];
      let elementIndex = 0;

      for (const el of Array.from(candidates)) {
        if (results.length >= maxElements) break;

        // Skip excluded elements
        if (excludeSelector && el.closest(excludeSelector)) continue;

        const role = el.getAttribute('role') || inferRole(el);
        if (!interactiveRoles.includes(role)) continue;

        // Check visibility
        const style = window.getComputedStyle(el);
        const htmlEl = el as HTMLElement;
        const isVisible = style.display !== 'none' &&
                          style.visibility !== 'hidden' &&
                          style.opacity !== '0' &&
                          htmlEl.offsetWidth > 0 &&
                          htmlEl.offsetHeight > 0;

        if (!includeHidden && !isVisible) continue;

        const rect = htmlEl.getBoundingClientRect();
        const boundingBox: BoundingBox = {
          x: rect.x,
          y: rect.y,
          width: rect.width,
          height: rect.height,
        };

        const attributes: Record<string, string> = {};
        for (const attr of includeAttributes) {
          const value = el.getAttribute(attr);
          if (value) attributes[attr] = value;
        }

        const name = el.getAttribute('aria-label') ||
                     el.getAttribute('aria-labelledby') ||
                     el.getAttribute('name') ||
                     el.getAttribute('title') ||
                     (el as HTMLInputElement).placeholder ||
                     (el.textContent ? el.textContent.trim().slice(0, 100) : '');

        const tagName = el.tagName.toLowerCase();
        const headingMatch = tagName.match(/^h([1-6])$/);

        const element: InteractiveElement = {
          id: `element_${elementIndex++}`,
          role,
          name: name || undefined,
          description: el.getAttribute('aria-description') || undefined,
          visible: isVisible,
          enabled: !el.hasAttribute('disabled') && !el.hasAttribute('readonly') && !el.hasAttribute('aria-disabled'),
          selected: el.hasAttribute('selected') || (el as HTMLOptionElement).selected || undefined,
          checked: (el as HTMLInputElement).checked || undefined,
          level: headingMatch ? parseInt(headingMatch[1], 10) : undefined,
          boundingBox,
          selector: selectorFor(el),
          attributes,
        };

        results.push(element);
      }

      return results;
    }, this.config);

    return elements;
  }

  private inferRole(element: Element): string {
    const tagName = element.tagName.toLowerCase();
    const type = (element as HTMLInputElement).type?.toLowerCase();
    
    const roleMap: Record<string, string> = {
      'a': 'link',
      'button': 'button',
      'input': type === 'checkbox' ? 'checkbox' : type === 'radio' ? 'radio' : 'textbox',
      'textarea': 'textbox',
      'select': 'combobox',
      'option': 'option',
      'h1': 'heading',
      'h2': 'heading',
      'h3': 'heading',
      'h4': 'heading',
      'h5': 'heading',
      'h6': 'heading',
      'img': 'img',
      'form': 'form',
      'nav': 'navigation',
      'main': 'main',
      'article': 'article',
      'section': 'region',
      'aside': 'complementary',
      'header': 'banner',
      'footer': 'contentinfo',
      'ul': 'list',
      'ol': 'list',
      'li': 'listitem',
      'table': 'table',
      'tr': 'row',
      'td': 'cell',
      'th': 'columnheader',
    };

    return roleMap[tagName] || 'generic';
  }

  private getHeadingLevel(element: Element): number | undefined {
    const tagName = element.tagName.toLowerCase();
    if (tagName.match(/^h[1-6]$/)) {
      return parseInt(tagName[1]);
    }
    const ariaLevel = element.getAttribute('aria-level');
    return ariaLevel ? parseInt(ariaLevel) : undefined;
  }

  private generateSelector(element: Element): string {
    // Try to generate a stable selector
    if (element.id) {
      return `#${element.id}`;
    }
    if (element.getAttribute('data-testid')) {
      return `[data-testid="${element.getAttribute('data-testid')}"]`;
    }
    if (element.getAttribute('name')) {
      return `[name="${element.getAttribute('name')}"]`;
    }
    
    // Fallback to tag + class
    const classes = element.className.split(' ').filter(c => c && !c.startsWith('_')).slice(0, 2);
    if (classes.length > 0) {
      return `${element.tagName.toLowerCase()}.${classes.join('.')}`;
    }
    
    return element.tagName.toLowerCase();
  }

  async extractTextContent(target: BrowserPage | BrowserFrame): Promise<string> {
    return target.evaluate((config: DOMExtractionConfig) => {
      const { excludeSelectors, maxTextLength } = config;
      const excludeSelector = excludeSelectors.join(', ');
      
      // Clone body to avoid modifying original
      const body = document.body.cloneNode(true) as HTMLElement;
      
      // Remove excluded elements
      for (const el of body.querySelectorAll(excludeSelector)) {
        el.remove();
      }
      
      // Get text content
      let text = body.innerText || '';
      
      // Normalize whitespace
      text = text.replace(/\s+/g, ' ').trim();
      
      // Truncate
      if (text.length > maxTextLength) {
        text = text.slice(0, maxTextLength) + '... [truncated]';
      }
      
      return text;
    }, this.config);
  }

  async extractDOMSnapshot(target: BrowserPage | BrowserFrame): Promise<string> {
    return target.evaluate((config: DOMExtractionConfig) => {
      const { excludeSelectors } = config;
      const excludeSelector = excludeSelectors.join(', ');
      
      const body = document.body.cloneNode(true) as HTMLElement;
      
      for (const el of body.querySelectorAll(excludeSelector)) {
        el.remove();
      }
      
      return body.outerHTML;
    }, this.config);
  }

  async extractAccessibilityTree(target: BrowserPage | BrowserFrame): Promise<AccessibilityNode | undefined> {
    try {
      const tree = await target.evaluate((): AccessibilityNode | null => {
        // Simplified DOM-derived tree; providers with AX support override this.
        const build = (node: Node): AccessibilityNode | null => {
          if (node.nodeType !== Node.ELEMENT_NODE) return null;
          const el = node as HTMLElement;
          const kids: AccessibilityNode[] = [];
          for (const child of Array.from(el.children)) {
            const c = build(child);
            if (c) kids.push(c);
          }
          return {
            role: el.getAttribute('role') || el.tagName.toLowerCase(),
            name: el.getAttribute('aria-label') || undefined,
            value: (el as HTMLInputElement).value || undefined,
            description: el.getAttribute('aria-description') || undefined,
            children: kids.length > 0 ? kids : undefined,
          };
        };
        return build(document.body);
      });
      return tree ?? undefined;
    } catch (error) {
      logger.warn('Failed to extract accessibility tree', { error: String(error) });
      return undefined;
    }
  }

  private buildAccessibilityTree(node: Node): AccessibilityNode | null {
    if (node.nodeType !== Node.ELEMENT_NODE) return null;
    
    const el = node as HTMLElement;
    const role = el.getAttribute('role') || this.inferRole(el);
    
    const children: AccessibilityNode[] = [];
    for (const child of el.children) {
      const childNode = this.buildAccessibilityTree(child);
      if (childNode) children.push(childNode);
    }
    
    return {
      role,
      name: el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || undefined,
      value: (el as HTMLInputElement).value || undefined,
      description: el.getAttribute('aria-description') || undefined,
      states: this.getAriaStates(el),
      children: children.length > 0 ? children : undefined,
    };
  }

  private getAriaStates(element: HTMLElement): string[] {
    const states: string[] = [];
    if (element.hasAttribute('aria-expanded')) states.push(element.getAttribute('aria-expanded') === 'true' ? 'expanded' : 'collapsed');
    if (element.hasAttribute('aria-selected')) states.push('selected');
    if (element.hasAttribute('aria-checked')) states.push(element.getAttribute('aria-checked') === 'true' ? 'checked' : 'unchecked');
    if (element.hasAttribute('aria-disabled')) states.push('disabled');
    if (element.hasAttribute('aria-hidden')) states.push('hidden');
    if (element.hasAttribute('aria-pressed')) states.push(element.getAttribute('aria-pressed') === 'true' ? 'pressed' : 'released');
    if (element.hasAttribute('aria-readonly')) states.push('readonly');
    if (element.hasAttribute('aria-required')) states.push('required');
    return states;
  }

  async extractScreenshot(target: BrowserPage | BrowserFrame): Promise<string> {
    // This would be implemented with actual screenshot logic
    // For now, return a placeholder
    return '';
  }

  private pruneElements(elements: InteractiveElement[]): InteractiveElement[] {
    // Remove duplicates based on bounding box overlap
    const unique: InteractiveElement[] = [];
    const seenBoxes = new Set<string>();
    
    for (const el of elements) {
      if (!el.boundingBox) continue;
      const boxKey = `${Math.round(el.boundingBox.x)},${Math.round(el.boundingBox.y)},${Math.round(el.boundingBox.width)},${Math.round(el.boundingBox.height)}`;
      if (!seenBoxes.has(boxKey)) {
        seenBoxes.add(boxKey);
        unique.push(el);
      }
    }
    
    return unique;
  }

  async extractStructured(target: BrowserPage | BrowserFrame, options: BrowserExtractOptions): Promise<unknown> {
    return target.evaluate((opts: BrowserExtractOptions) => {
      const { selector, attribute, multiple } = opts;
      const elements = document.querySelectorAll(selector);
      if (!elements.length) return multiple ? [] : null;

      if (multiple) {
        return Array.from(elements).map(el => {
          if (attribute) return el.getAttribute(attribute);
          return el.textContent ? el.textContent.trim() : '';
        });
      }

      const el = elements[0];
      if (attribute) return el.getAttribute(attribute);
      return el.textContent ? el.textContent.trim() : '';
    }, options);
  }

  async extractTables(target: BrowserPage | BrowserFrame): Promise<Array<{ headers: (string | null)[]; rows: (string | null)[][] }>> {
    return target.evaluate((): Array<{ headers: (string | null)[]; rows: (string | null)[][] }> => {
      const tables = document.querySelectorAll('table');
      return Array.from(tables).map(table => {
        const headers = Array.from(table.querySelectorAll('th')).map(th => th.textContent ? th.textContent.trim() : null);
        const rows = Array.from(table.querySelectorAll('tr')).map(row =>
          Array.from(row.querySelectorAll('td, th')).map(cell => cell.textContent ? cell.textContent.trim() : null)
        );
        return { headers, rows };
      });
    });
  }

  async extractLinks(target: BrowserPage | BrowserFrame): Promise<{ text: string; href: string }[]> {
    return target.evaluate((): { text: string; href: string }[] => {
      return Array.from(document.querySelectorAll('a[href]')).map(a => ({
        text: a.textContent ? a.textContent.trim() : '',
        href: a.getAttribute('href') || '',
      }));
    });
  }

  async extractForms(target: BrowserPage | BrowserFrame): Promise<Record<string, unknown>[]> {
    return target.evaluate((): Record<string, unknown>[] => {
      return Array.from(document.querySelectorAll('form')).map(form => {
        const fields = Array.from(form.querySelectorAll('input, select, textarea')).map(field => ({
          name: field.getAttribute('name'),
          type: (field as HTMLInputElement).type,
          value: (field as HTMLInputElement).value,
          placeholder: field.getAttribute('placeholder'),
          required: field.hasAttribute('required'),
        }));
        return {
          action: form.getAttribute('action'),
          method: form.getAttribute('method'),
          fields,
        };
      });
    });
  }
}

export const domExtractor = new DOMExtractor();