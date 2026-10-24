begin;

-- Preserve duplicate shopping rows by folding their quantities and notes into
-- the oldest row before enforcing the natural key.
with duplicate_groups as (
    select
        item_prior_id,
        unit,
        target_location,
        min(id) as keep_id,
        sum(quantity) as quantity,
        case
            when count(coalesce(quantity_pz, case when lower(unit) = 'pz' then quantity end)) = 0 then null
            else sum(coalesce(quantity_pz, case when lower(unit) = 'pz' then quantity end))
        end as quantity_pz,
        case
            when count(coalesce(measure_quantity, case when lower(unit) <> 'pz' then quantity end)) = 0 then null
            else sum(coalesce(measure_quantity, case when lower(unit) <> 'pz' then quantity end))
        end as measure_quantity,
        string_agg(nullif(notes, ''), '; ' order by id) as notes,
        array_agg(id order by id) as ids
    from public.shopping_items
    group by item_prior_id, unit, target_location
    having count(*) > 1
), updated_groups as (
    update public.shopping_items s
    set quantity = d.quantity,
        quantity_pz = d.quantity_pz,
        measure_quantity = d.measure_quantity,
        notes = d.notes
    from duplicate_groups d
    where s.id = d.keep_id
    returning d.keep_id, d.ids
)
delete from public.shopping_items s
using updated_groups g
where s.id = any(g.ids)
  and s.id <> g.keep_id;

create unique index if not exists idx_shopping_unique_item_unit_location
    on public.shopping_items(item_prior_id, unit, target_location);

create or replace function public.add_or_increment_shopping_item(
    p_item_prior_id bigint,
    p_quantity double precision,
    p_unit text,
    p_quantity_pz double precision,
    p_measure_quantity double precision,
    p_target_location text,
    p_notes text
)
returns bigint
language plpgsql
security invoker
as $$
declare
    v_id bigint;
begin
    insert into public.shopping_items (
        item_prior_id, quantity, unit, quantity_pz, measure_quantity,
        target_location, notes
    ) values (
        p_item_prior_id, p_quantity, p_unit, p_quantity_pz, p_measure_quantity,
        p_target_location, p_notes
    )
    on conflict (item_prior_id, unit, target_location) do update
    set quantity = public.shopping_items.quantity + excluded.quantity,
        quantity_pz = case
            when excluded.quantity_pz is not null and public.shopping_items.quantity_pz is not null
                then public.shopping_items.quantity_pz + excluded.quantity_pz
            else public.shopping_items.quantity_pz
        end,
        measure_quantity = case
            when excluded.measure_quantity is not null and public.shopping_items.measure_quantity is not null
                then public.shopping_items.measure_quantity + excluded.measure_quantity
            else public.shopping_items.measure_quantity
        end,
        notes = case
            when coalesce(public.shopping_items.notes, '') = '' then coalesce(excluded.notes, '')
            when coalesce(excluded.notes, '') = '' then public.shopping_items.notes
            else public.shopping_items.notes || '; ' || excluded.notes
        end
    returning id into v_id;

    return v_id;
end;
$$;

create or replace function public.adjust_inventory_quantity(
    p_item_id bigint,
    p_direction text,
    p_quantity double precision,
    p_unit text,
    p_changed_on date
)
returns jsonb
language plpgsql
security invoker
as $$
declare
    v_item public.inventory_items%rowtype;
    v_typical_quantity double precision;
    v_typical_unit text;
    v_inventory_display_unit text;
    v_direction text := lower(coalesce(p_direction, ''));
    v_unit text;
    v_previous_quantity double precision;
    v_quantity double precision;
    v_quantity_delta double precision;
    v_quantity_pz double precision;
    v_measure_quantity double precision;
    v_measure_unit text;
    v_legacy_quantity double precision;
    v_legacy_unit text;
    v_step double precision := 1;
    v_from_base text;
    v_to_base text;
    v_from_factor double precision;
    v_to_factor double precision;
    v_display_mode text;
    v_total double precision;
begin
    select i.* into v_item
    from public.inventory_items i
    where i.id = p_item_id
    for update;

    if not found then
        return jsonb_build_object('ok', false, 'error', 'Prodotto non trovato.');
    end if;

    select p.typical_quantity, p.typical_unit, p.inventory_display_unit
    into v_typical_quantity, v_typical_unit, v_inventory_display_unit
    from public.item_prior p
    where p.id = v_item.item_prior_id;

    v_unit := coalesce(nullif(p_unit, ''), v_item.unit, 'pz');
    if lower(v_unit) = 'pz' then
        v_previous_quantity := coalesce(
            v_item.quantity_pz,
            case when lower(v_item.unit) = 'pz' then v_item.quantity end,
            v_item.quantity
        );
    else
        v_previous_quantity := coalesce(
            v_item.measure_quantity,
            case when lower(v_item.unit) <> 'pz' then v_item.quantity end,
            case
                when v_item.quantity_pz is not null
                 and v_typical_quantity is not null
                 and v_typical_quantity <> 0
                 and lower(coalesce(v_typical_unit, '')) in ('g', 'ml', 'kg', 'l')
                    then v_item.quantity_pz * v_typical_quantity
            end,
            v_item.quantity
        );
    end if;

    if v_direction = 'edit' then
        if p_quantity is null or p_quantity < 0 or v_unit not in ('pz', 'g', 'ml', 'l', 'kg') then
            return jsonb_build_object('ok', false, 'error', 'Inserisci una quantità non negativa e un''unità valida.');
        end if;
        v_quantity := p_quantity;
    elsif v_direction in ('inc', 'dec') then
        if lower(v_unit) in ('pz', 'pc', 'pezzo', 'pezzi', 'unita', 'u') then
            v_step := 1;
        elsif lower(v_unit) in ('g', 'gr', 'grammo', 'grammi', 'ml') then
            v_step := 100;
        else
            v_step := 1;
        end if;
        v_quantity := round((v_previous_quantity + case when v_direction = 'inc' then v_step else -v_step end)::numeric, 4)::double precision;
        if v_quantity < 0 then
            return jsonb_build_object('ok', false, 'error', 'La quantita'' non puo'' scendere sotto zero.');
        end if;
    else
        return jsonb_build_object('ok', false, 'error', 'Azione quantita'' non valida.');
    end if;

    v_quantity_delta := v_quantity - v_previous_quantity;
    if lower(v_unit) = 'pz' then
        v_quantity_pz := v_quantity;
        if v_typical_quantity is not null and v_typical_quantity <> 0
           and lower(coalesce(v_typical_unit, '')) in ('g', 'ml', 'kg', 'l') then
            v_measure_quantity := v_quantity * v_typical_quantity;
            v_measure_unit := v_typical_unit;
        end if;
    else
        v_measure_quantity := v_quantity;
        v_measure_unit := v_unit;
        v_from_base := case when lower(v_unit) in ('kg', 'l', 'g', 'ml') then 'g' else lower(v_unit) end;
        v_to_base := case when lower(coalesce(v_typical_unit, '')) in ('kg', 'l', 'g', 'ml') then 'g' else lower(v_typical_unit) end;
        v_from_factor := case when lower(v_unit) in ('kg', 'l') then 1000.0 else 1.0 end;
        v_to_factor := case when lower(coalesce(v_typical_unit, '')) in ('kg', 'l') then 1000.0 else 1.0 end;
        if v_typical_quantity is not null and v_typical_quantity <> 0
           and lower(coalesce(v_typical_unit, '')) in ('g', 'ml', 'kg', 'l')
           and v_from_base = v_to_base and v_quantity <> 0 then
            v_quantity_pz := (v_quantity * v_from_factor) / (v_typical_quantity * v_to_factor);
        end if;
    end if;

    v_display_mode := case
        when v_item.recipe_id is not null then 'pz'
        else coalesce(v_inventory_display_unit, case when lower(v_unit) = 'pz' then 'pz' else 'measure' end)
    end;
    if v_display_mode = 'pz' and v_quantity_pz is not null then
        v_legacy_quantity := v_quantity_pz;
        v_legacy_unit := 'pz';
    else
        v_legacy_quantity := v_measure_quantity;
        v_legacy_unit := coalesce(v_measure_unit, 'pz');
    end if;

    update public.inventory_items
    set quantity = coalesce(v_legacy_quantity, 0),
        unit = v_legacy_unit,
        quantity_pz = v_quantity_pz,
        measure_quantity = v_measure_quantity,
        updated_at = now()
    where id = p_item_id;

    if v_quantity_delta <> 0 and v_item.recipe_id is null then
        insert into public.inventory_quantity_changes (
            inventory_item_id, quantity, unit, changed_on
        ) values (
            p_item_id, v_quantity_delta, v_unit, p_changed_on
        );
    end if;

    select coalesce(sum(
        case
            when (case when lower(unit) in ('g', 'ml', 'kg', 'l') then 'measure' else lower(unit) end)
               = (case when lower(v_unit) in ('g', 'ml', 'kg', 'l') then 'measure' else lower(v_unit) end)
            then quantity
                 * (case when lower(unit) in ('kg', 'l') then 1000.0 else 1.0 end)
                 / (case when lower(v_unit) in ('kg', 'l') then 1000.0 else 1.0 end)
            else 0.0
        end
    ), 0.0)
    into v_total
    from public.inventory_quantity_changes
    where inventory_item_id = p_item_id
      and changed_on = p_changed_on;

    return jsonb_build_object(
        'ok', true,
        'quantity', v_quantity,
        'unit', v_unit,
        'previous_quantity', v_previous_quantity,
        'today_quantity_change', v_total
    );
end;
$$;

create or replace function public.complete_shopping_items(
    p_item_ids bigint[],
    p_purchased_at timestamptz,
    p_today date
)
returns jsonb
language plpgsql
security invoker
as $$
declare
    v_item record;
    v_existing public.inventory_items%rowtype;
    v_inventory_id bigint;
    v_expiry date;
    v_expiry_estimated integer;
    v_quantity_pz double precision;
    v_measure_quantity double precision;
    v_measure_unit text;
    v_addition double precision;
    v_legacy_quantity double precision;
    v_legacy_unit text;
    v_change_quantity double precision;
    v_change_unit text;
    v_results jsonb := '[]'::jsonb;
    v_is_household boolean;
begin
    for v_item in
        select s.*, p.name, p.category, p.typical_quantity, p.typical_unit,
               p.typical_shelf_life_days, p.inventory_display_unit
        from public.shopping_items s
        join public.item_prior p on p.id = s.item_prior_id
        where s.id = any(coalesce(p_item_ids, '{}'::bigint[]))
        order by array_position(p_item_ids, s.id)
        for update of s
    loop
        if coalesce(v_item.quantity, 0) <= 0 then
            v_results := v_results || jsonb_build_array(jsonb_build_object(
                'id', v_item.id, 'name', v_item.name, 'completed', false,
                'error', 'La quantita'' acquistata deve essere maggiore di zero.'
            ));
            continue;
        end if;

        if v_item.target_location not in ('frigo', 'dispensa', 'freezer') then
            v_results := v_results || jsonb_build_array(jsonb_build_object(
                'id', v_item.id, 'name', v_item.name, 'completed', false,
                'error', 'Destinazione non valida.'
            ));
            continue;
        end if;

        v_is_household := lower(trim(coalesce(v_item.category, ''))) = 'casalinghi';
        if v_is_household then
            insert into public.items_history (
                item_prior_id, inventory_item_id, purchased_at, quantity, unit,
                quantity_pz, measure_quantity, cost, target_location, notes
            ) values (
                v_item.item_prior_id, null, p_purchased_at, 1, 'pz',
                1,
                case when v_item.typical_quantity is not null and v_item.typical_quantity <> 0
                           and lower(coalesce(v_item.typical_unit, 'pz')) in ('g', 'ml', 'kg', 'l')
                     then v_item.typical_quantity else null end,
                null, null, coalesce(v_item.notes, '')
            );
            delete from public.shopping_items where id = v_item.id;
            v_results := v_results || jsonb_build_array(jsonb_build_object(
                'id', v_item.id, 'name', v_item.name, 'completed', true
            ));
            continue;
        end if;

        if v_item.typical_shelf_life_days is null or v_item.typical_shelf_life_days = 0 then
            v_expiry := null;
            v_expiry_estimated := 0;
        else
            v_expiry := p_today + v_item.typical_shelf_life_days;
            v_expiry_estimated := 1;
        end if;

        if lower(v_item.unit) = 'pz' then
            v_quantity_pz := v_item.quantity;
            v_measure_quantity := case
                when v_item.typical_quantity is not null and v_item.typical_quantity <> 0
                     and lower(coalesce(v_item.typical_unit, 'pz')) in ('g', 'ml', 'kg', 'l')
                    then v_item.quantity * v_item.typical_quantity
                else null
            end;
            v_measure_unit := case when v_measure_quantity is not null then v_item.typical_unit else null end;
        else
            v_measure_quantity := v_item.quantity;
            v_measure_unit := v_item.unit;
            if v_item.typical_quantity is not null and v_item.typical_quantity <> 0
               and lower(coalesce(v_item.typical_unit, 'pz')) in ('g', 'ml', 'kg', 'l')
               and lower(v_item.unit) in ('g', 'ml', 'kg', 'l') then
                v_quantity_pz := (v_item.quantity
                    * case when lower(v_item.unit) in ('kg', 'l') then 1000.0 else 1.0 end)
                    / (v_item.typical_quantity
                    * case when lower(v_item.typical_unit) in ('kg', 'l') then 1000.0 else 1.0 end);
            else
                v_quantity_pz := null;
            end if;
        end if;

        v_inventory_id := null;
        select i.* into v_existing
        from public.inventory_items i
        where i.item_prior_id = v_item.item_prior_id
          and i.quantity > 0
          and ((i.expiry_date is null and v_expiry is null)
               or (i.expiry_date is not null and v_expiry is not null and abs(i.expiry_date - v_expiry) <= 5))
        order by case when i.expiry_date is null or v_expiry is null then 0 else abs(i.expiry_date - v_expiry) end,
                 i.id
        limit 1
        for update;

        if found then
            -- Match merge_item_with_prior()'s compatibility backfill for rows
            -- created before quantity_pz / measure_quantity were introduced.
            if v_existing.quantity_pz is null and v_existing.measure_quantity is null then
                if lower(v_existing.unit) = 'pz' then
                    v_existing.quantity_pz := v_existing.quantity;
                else
                    v_existing.measure_quantity := v_existing.quantity;
                end if;
            end if;
            if v_existing.quantity_pz is not null
               and v_existing.measure_quantity is null
               and v_item.typical_quantity is not null
               and v_item.typical_quantity <> 0
               and lower(coalesce(v_item.typical_unit, '')) in ('g', 'ml', 'kg', 'l') then
                v_existing.measure_quantity := v_existing.quantity_pz * v_item.typical_quantity;
            end if;
            v_measure_unit := case
                when v_existing.quantity_pz is not null and v_existing.measure_quantity is not null
                     and lower(coalesce(v_item.typical_unit, '')) in ('g', 'ml', 'kg', 'l')
                    then v_item.typical_unit
                when lower(v_existing.unit) <> 'pz' then v_existing.unit
                else null
            end;
            if v_quantity_pz is not null and v_existing.quantity_pz is not null then
                v_existing.quantity_pz := coalesce(v_existing.quantity_pz, 0) + v_quantity_pz;
                v_change_quantity := v_quantity_pz;
                v_change_unit := case
                    when v_item.inventory_display_unit = 'pz' then 'pz'
                    else coalesce(v_measure_unit, v_existing.unit, 'pz')
                end;
            elsif v_measure_quantity is not null and v_existing.measure_quantity is not null
                  and v_measure_unit is not null
                  and (case when lower(v_item.unit) in ('g', 'ml', 'kg', 'l') then 'measure' else lower(v_item.unit) end)
                      = (case when lower(v_measure_unit) in ('g', 'ml', 'kg', 'l') then 'measure' else lower(v_measure_unit) end) then
                v_addition := v_measure_quantity
                    * case when lower(v_item.unit) in ('kg', 'l') then 1000.0 else 1.0 end
                    / case when lower(v_measure_unit) in ('kg', 'l') then 1000.0 else 1.0 end;
                v_existing.measure_quantity := v_existing.measure_quantity + v_addition;
                v_change_quantity := v_addition;
                v_change_unit := v_measure_unit;
            else
                v_existing.id := null;
            end if;

            if v_existing.id is not null then
                if v_item.inventory_display_unit = 'pz' and v_existing.quantity_pz is not null then
                    v_legacy_quantity := v_existing.quantity_pz;
                    v_legacy_unit := 'pz';
                else
                    v_legacy_quantity := v_existing.measure_quantity;
                    v_legacy_unit := coalesce(v_measure_unit, v_existing.unit, 'pz');
                end if;
                update public.inventory_items
                set quantity = coalesce(v_legacy_quantity, 0),
                    unit = v_legacy_unit,
                    quantity_pz = v_existing.quantity_pz,
                    measure_quantity = v_existing.measure_quantity,
                    updated_at = now()
                where id = v_existing.id;
                v_inventory_id := v_existing.id;
                insert into public.inventory_quantity_changes (
                    inventory_item_id, quantity, unit, changed_on
                ) values (v_inventory_id, v_change_quantity, v_change_unit, p_today);
            end if;
        end if;

        if v_inventory_id is null then
            if v_item.inventory_display_unit = 'pz' and v_quantity_pz is not null then
                v_legacy_quantity := v_quantity_pz;
                v_legacy_unit := 'pz';
            else
                v_legacy_quantity := v_measure_quantity;
                v_legacy_unit := coalesce(v_measure_unit, v_item.unit, 'pz');
            end if;
            insert into public.inventory_items (
                item_prior_id, quantity, unit, quantity_pz, measure_quantity,
                location, preparation_status, expiry_date, expiry_estimated,
                notes, created_at, updated_at
            ) values (
                v_item.item_prior_id, coalesce(v_legacy_quantity, 0), v_legacy_unit,
                v_quantity_pz, v_measure_quantity, v_item.target_location,
                'none', v_expiry, v_expiry_estimated, coalesce(v_item.notes, ''), now(), now()
            ) returning id into v_inventory_id;
            insert into public.inventory_quantity_changes (
                inventory_item_id, quantity, unit, changed_on
            ) values (v_inventory_id, v_item.quantity, v_item.unit, p_today);
        end if;

        insert into public.items_history (
            item_prior_id, inventory_item_id, purchased_at, quantity, unit,
            quantity_pz, measure_quantity, cost, target_location, notes
        ) values (
            v_item.item_prior_id, v_inventory_id, p_purchased_at, v_item.quantity,
            v_item.unit, v_quantity_pz, v_measure_quantity, null,
            v_item.target_location, coalesce(v_item.notes, '')
        );
        delete from public.shopping_items where id = v_item.id;
        v_results := v_results || jsonb_build_array(jsonb_build_object(
            'id', v_item.id, 'name', v_item.name, 'completed', true
        ));
    end loop;

    return v_results;
end;
$$;

commit;
