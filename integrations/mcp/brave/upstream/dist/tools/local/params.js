import { z } from 'zod';
export const LocalPoisParams = z.object({
    ids: z.array(z.string()).describe('List of location IDs for which to fetch POIs'),
});
export const LocalDescriptionsParams = z.object({
    ids: z.array(z.string()).describe('List of location IDs for which to fetch descriptions'),
});
