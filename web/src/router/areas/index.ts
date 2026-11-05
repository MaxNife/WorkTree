// The five areas in sidebar order. Each module owns its routes, sidebar entries and palette commands.
import type { AreaModule } from '../types'
import * as admin from './admin'
import * as data from './data'
import * as inbox from './inbox'
import * as operations from './operations'
import * as studio from './studio'

export const AREAS: AreaModule[] = [operations, inbox, studio, data, admin]
