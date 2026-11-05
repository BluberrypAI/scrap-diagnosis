# 소재별 판정표 — 목록

`tools/material_tables.py`가 엔진으로 만든 표입니다. 표마다 끝의 '검토' 칸에 확인 표시를 합니다.

- 소재 97종, 행 4305개, 멈춤(시험·기관 확인 등) 233행
- 번호를 목록에서 골라야 하는 소재: abs, absorbent, acid_lcd_semi, acid_other, activated_carbon, adsorbent, alkali_other, ammonia_solution, aqua_buoy, battery_cathode, battery_drive, battery_ev, battery_fuel_cell, battery_primary, battery_secondary_other, bf_slag, bottom_ash_business, catalyst_metal, catalyst_nonmetal, caustic_solution, coated_wire, cutting_oil_insoluble, cutting_oil_soluble, dust_cement, dust_other, dust_power, dust_steel, eee_industrial, eps, ferrous_scrap, fiber_natural, fiber_synthetic, filter_sand, fishing_net, fly_ash_business, foundry_chemical, foundry_clay, fuel_oil, glass, glass_fiber, h2so4, hcl, hf, hno3, insulating_oil, ion_exchange_resin, koh_solid, lacquer, lube_oil, machine_oil, metal_can, metal_container, mixed_ash_business, mixed_inseparable, naoh_solid, nonferrous_scrap, oil_filter, other_resin, paint_oil, paint_water, paper, pe, pet, phenol_resin, plastic_packaging, pp, ps, pu_foam, pvc, refractory, rubber, sandblast, silica_fume, slag_aluminum, slag_lead, slag_nonferrous_other, slag_zinc, sludge_proc_glass_etching, sludge_proc_inorganic, sludge_proc_organic, sludge_proc_pulp_paper, sludge_proc_silicon, sludge_proc_unknown, sludge_ww_inorganic, sludge_ww_organic, sludge_ww_pulp_paper, sludge_ww_stone, sludge_ww_unknown, solar_panel, solvent_halogen, solvent_other, steel_slag, tire_auto, wood_byproduct, wood_clean, wood_preservative, wood_treated
- 지정 사유가 여러 개인 행이 있는 소재(번호가 한쪽으로 좁혀졌는지 검토): abs, absorbent, acid_lcd_semi, acid_other, activated_carbon, adsorbent, alkali_other, ammonia_solution, bottom_ash_business, catalyst_metal, catalyst_nonmetal, caustic_solution, cutting_oil_insoluble, cutting_oil_soluble, dust_cement, dust_other, dust_power, dust_steel, filter_sand, fly_ash_business, foundry_chemical, foundry_clay, fuel_oil, h2so4, hcl, hf, hno3, insulating_oil, ion_exchange_resin, koh_solid, lacquer, lube_oil, machine_oil, mixed_ash_business, naoh_solid, oil_filter, other_resin, paint_oil, paint_water, pe, pet, phenol_resin, pp, ps, pvc, refractory, rubber, sandblast, silica_fume, slag_aluminum, slag_lead, slag_nonferrous_other, slag_zinc, sludge_proc_glass_etching, sludge_proc_inorganic, sludge_proc_organic, sludge_proc_pulp_paper, sludge_proc_silicon, sludge_proc_unknown, sludge_ww_inorganic, sludge_ww_organic, sludge_ww_pulp_paper, sludge_ww_stone, sludge_ww_unknown, solvent_halogen, solvent_other, steel_slag, tire_auto
- 일부만 펼친 소재: 없음

| 묶음 | 소재 | 행 | 번호 선택 | 사유 여럿 |
|---|---|---|---|---|
| 플라스틱·고무 | [PP(폴리프로필렌)](pp.md) | 27 | 예 | 예 |
| 플라스틱·고무 | [PE(폴리에틸렌)](pe.md) | 27 | 예 | 예 |
| 플라스틱·고무 | [PET](pet.md) | 27 | 예 | 예 |
| 플라스틱·고무 | [PS(폴리스티렌, 발포 아님)](ps.md) | 24 | 예 | 예 |
| 플라스틱·고무 | [ABS 수지](abs.md) | 24 | 예 | 예 |
| 플라스틱·고무 | [페놀수지](phenol_resin.md) | 24 | 예 | 예 |
| 플라스틱·고무 | [그 밖의 합성수지(PC, 나일론 등)](other_resin.md) | 24 | 예 | 예 |
| 플라스틱·고무 | [PVC(염화비닐)](pvc.md) | 24 | 예 | 예 |
| 플라스틱·고무 | [폴리우레탄폼](pu_foam.md) | 12 | 예 |  |
| 플라스틱·고무 | [발포합성수지(스티로폼)](eps.md) | 12 | 예 |  |
| 플라스틱·고무 | [플라스틱 포장재](plastic_packaging.md) | 12 | 예 |  |
| 플라스틱·고무 | [폐어망](fishing_net.md) | 12 | 예 |  |
| 플라스틱·고무 | [양식용 부자](aqua_buoy.md) | 12 | 예 |  |
| 플라스틱·고무 | [합성고무](rubber.md) | 24 | 예 | 예 |
| 금속 | [고철(철 스크랩)](ferrous_scrap.md) | 16 | 예 |  |
| 금속 | [비철금속(구리·알루미늄 등)](nonferrous_scrap.md) | 16 | 예 |  |
| 금속 | [폐금속캔](metal_can.md) | 31 | 예 |  |
| 금속 | [폐금속용기(드럼 등)](metal_container.md) | 16 | 예 |  |
| 광재(슬래그) | [고로슬래그(철광석 고로)](bf_slag.md) | 10 | 예 |  |
| 광재(슬래그) | [제강슬래그](steel_slag.md) | 81 | 예 | 예 |
| 광재(슬래그) | [알루미늄 제조공정 광재](slag_aluminum.md) | 81 | 예 | 예 |
| 광재(슬래그) | [납 열처리·야금공정 광재](slag_lead.md) | 81 | 예 | 예 |
| 광재(슬래그) | [아연 열처리공정 광재](slag_zinc.md) | 81 | 예 | 예 |
| 광재(슬래그) | [그 밖의 비철금속 제련 광재](slag_nonferrous_other.md) | 81 | 예 | 예 |
| 분진·소각재 | [제철공정 분진](dust_steel.md) | 90 | 예 | 예 |
| 분진·소각재 | [시멘트 제조공정 분진](dust_cement.md) | 90 | 예 | 예 |
| 분진·소각재 | [발전시설 분진](dust_power.md) | 90 | 예 | 예 |
| 분진·소각재 | [실리카 퓸(규소철 제조 분진)](silica_fume.md) | 90 | 예 | 예 |
| 분진·소각재 | [그 밖의 분진(집진기 분진 등)](dust_other.md) | 90 | 예 | 예 |
| 분진·소각재 | [사업장폐기물 소각시설 비산재](fly_ash_business.md) | 80 | 예 | 예 |
| 분진·소각재 | [사업장폐기물 소각시설 바닥재](bottom_ash_business.md) | 80 | 예 | 예 |
| 분진·소각재 | [사업장폐기물 소각시설 소각재(바닥재+비산재)](mixed_ash_business.md) | 80 | 예 | 예 |
| 주물사·폐사·내화물 | [점토점결 폐주물사](foundry_clay.md) | 81 | 예 | 예 |
| 주물사·폐사·내화물 | [화학점결 폐주물사](foundry_chemical.md) | 81 | 예 | 예 |
| 주물사·폐사·내화물 | [샌드블라스트 폐사](sandblast.md) | 81 | 예 | 예 |
| 주물사·폐사·내화물 | [폐여과사](filter_sand.md) | 81 | 예 | 예 |
| 주물사·폐사·내화물 | [폐내화물](refractory.md) | 81 | 예 | 예 |
| 오니(슬러지) | [펄프·제지 폐수처리 오니](sludge_ww_pulp_paper.md) | 128 | 예 | 예 |
| 오니(슬러지) | [석재·골재 생산 폐수처리 오니](sludge_ww_stone.md) | 128 | 예 | 예 |
| 오니(슬러지) | [그 밖의 폐수처리 오니(유기성)](sludge_ww_organic.md) | 128 | 예 | 예 |
| 오니(슬러지) | [그 밖의 폐수처리 오니(무기성)](sludge_ww_inorganic.md) | 128 | 예 | 예 |
| 오니(슬러지) | [폐수처리 오니(유기성·무기성 모름)](sludge_ww_unknown.md) | 128 | 예 | 예 |
| 오니(슬러지) | [펄프·제지 공정 오니](sludge_proc_pulp_paper.md) | 128 | 예 | 예 |
| 오니(슬러지) | [유리식각 공정 오니](sludge_proc_glass_etching.md) | 128 | 예 | 예 |
| 오니(슬러지) | [실리콘 (제조)공정 오니](sludge_proc_silicon.md) | 128 | 예 | 예 |
| 오니(슬러지) | [그 밖의 공정 오니(유기성)](sludge_proc_organic.md) | 128 | 예 | 예 |
| 오니(슬러지) | [그 밖의 공정 오니(무기성)](sludge_proc_inorganic.md) | 128 | 예 | 예 |
| 오니(슬러지) | [공정 오니(유기성·무기성 모름)](sludge_proc_unknown.md) | 128 | 예 | 예 |
| 기름 | [폐윤활유](lube_oil.md) | 4 | 예 | 예 |
| 기름 | [비수용성 절삭유·연마유·열처리유](cutting_oil_insoluble.md) | 4 | 예 | 예 |
| 기름 | [기계유·작동유(유압유 등)](machine_oil.md) | 4 | 예 | 예 |
| 기름 | [폐연료유](fuel_oil.md) | 4 | 예 | 예 |
| 기름 | [폐오일필터](oil_filter.md) | 8 | 예 | 예 |
| 기름 | [폐절연유(변압기유)](insulating_oil.md) | 4 | 예 | 예 |
| 기름 | [수용성 절삭유·그리스·방청유 등](cutting_oil_soluble.md) | 4 | 예 | 예 |
| 산·알칼리 | [폐염산](hcl.md) | 12 | 예 | 예 |
| 산·알칼리 | [폐황산](h2so4.md) | 12 | 예 | 예 |
| 산·알칼리 | [폐질산](hno3.md) | 12 | 예 | 예 |
| 산·알칼리 | [폐불산](hf.md) | 12 | 예 | 예 |
| 산·알칼리 | [LCD·반도체 공정 폐산](acid_lcd_semi.md) | 12 | 예 | 예 |
| 산·알칼리 | [그 밖의 폐산](acid_other.md) | 12 | 예 | 예 |
| 산·알칼리 | [폐가성소다수(수산화나트륨 수용액)](caustic_solution.md) | 12 | 예 | 예 |
| 산·알칼리 | [폐암모니아수](ammonia_solution.md) | 12 | 예 | 예 |
| 산·알칼리 | [고체 수산화나트륨](naoh_solid.md) | 5 | 예 | 예 |
| 산·알칼리 | [고체 수산화칼륨](koh_solid.md) | 5 | 예 | 예 |
| 산·알칼리 | [그 밖의 폐알칼리(액체)](alkali_other.md) | 12 | 예 | 예 |
| 용제·페인트 | [할로겐족 유기용제(TCE, 염화메틸렌 등)](solvent_halogen.md) | 9 | 예 | 예 |
| 용제·페인트 | [그 밖의 유기용제(시너, 아세톤, IPA 등)](solvent_other.md) | 9 | 예 | 예 |
| 용제·페인트 | [유성 페인트](paint_oil.md) | 10 | 예 | 예 |
| 용제·페인트 | [수성 페인트](paint_water.md) | 10 | 예 | 예 |
| 용제·페인트 | [락카(래커)](lacquer.md) | 10 | 예 | 예 |
| 목재·종이·섬유·유리 | [깨끗한 폐목재(목재 포장재·팔레트·전선드럼 등)](wood_clean.md) | 16 | 예 |  |
| 목재·종이·섬유·유리 | [접착제·페인트·기름 등이 사용된 폐목재](wood_treated.md) | 16 | 예 |  |
| 목재·종이·섬유·유리 | [방부제·할로겐족 처리 폐목재](wood_preservative.md) | 16 | 예 |  |
| 목재·종이·섬유·유리 | [원목 가공 부산물(톱밥·대패밥·껍질)](wood_byproduct.md) | 16 | 예 |  |
| 목재·종이·섬유·유리 | [폐지(종이류)](paper.md) | 16 | 예 |  |
| 목재·종이·섬유·유리 | [폐천연섬유](fiber_natural.md) | 16 | 예 |  |
| 목재·종이·섬유·유리 | [폐합성섬유](fiber_synthetic.md) | 16 | 예 |  |
| 목재·종이·섬유·유리 | [폐유리](glass.md) | 16 | 예 |  |
| 목재·종이·섬유·유리 | [폐유리섬유](glass_fiber.md) | 16 | 예 |  |
| 촉매·흡착제 | [금속성 폐촉매](catalyst_metal.md) | 81 | 예 | 예 |
| 촉매·흡착제 | [비금속성 폐촉매](catalyst_nonmetal.md) | 81 | 예 | 예 |
| 촉매·흡착제 | [폐이온교환수지](ion_exchange_resin.md) | 81 | 예 | 예 |
| 촉매·흡착제 | [폐활성탄](activated_carbon.md) | 96 | 예 | 예 |
| 촉매·흡착제 | [폐흡착제](adsorbent.md) | 96 | 예 | 예 |
| 촉매·흡착제 | [폐흡수제(기름 흡착포 등)](absorbent.md) | 96 | 예 | 예 |
| 제품·복합물 | [합성수지 피복 폐전선](coated_wire.md) | 12 | 예 |  |
| 제품·복합물 | [산업용 폐전기전자제품](eee_industrial.md) | 16 | 예 |  |
| 제품·복합물 | [자동차 폐타이어](tire_auto.md) | 24 | 예 | 예 |
| 제품·복합물 | [태양광 폐패널](solar_panel.md) | 16 | 예 |  |
| 제품·복합물 | [폐일차전지](battery_primary.md) | 11 | 예 |  |
| 제품·복합물 | [전기자동차 폐이차전지](battery_ev.md) | 11 | 예 |  |
| 제품·복합물 | [구동용 폐이차전지(전기차 외)](battery_drive.md) | 11 | 예 |  |
| 제품·복합물 | [폐양극활물질(양극재·전구체 공정 포함)](battery_cathode.md) | 11 | 예 |  |
| 제품·복합물 | [폐연료전지](battery_fuel_cell.md) | 11 | 예 |  |
| 제품·복합물 | [그 밖의 폐이차전지](battery_secondary_other.md) | 11 | 예 |  |
| 목록에 없거나 섞인 것 | [여러 소재가 섞여 나누기 어려움](mixed_inseparable.md) | 16 | 예 |  |
